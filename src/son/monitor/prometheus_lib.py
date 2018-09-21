"""
Copyright (c) 2015 SONATA-NFV
ALL RIGHTS RESERVED.
Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at
    http://www.apache.org/licenses/LICENSE-2.0
Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
Neither the name of the SONATA-NFV [, ANY ADDITIONAL AFFILIATION]
nor the names of its contributors may be used to endorse or promote
products derived from this software without specific prior written
permission.
This work has been performed in the framework of the SONATA project,
funded by the European Commission under Grant number 671517 through
the Horizon 2020 and 5G-PPP programmes. The authors would like to
acknowledge the contributions of their colleagues of the SONATA
partner consortium (www.sonata-nfv.eu).
"""

"""
Prometheus API helper functions
(c) 2016 by Steven Van Rossem <steven.vanrossem@intec.ugent.be>
"""

import requests
import logging
logging.getLogger("requests").setLevel(logging.WARNING)

import pkg_resources
import os
from son.profile.helper import read_yaml

from scipy.stats import t
import numpy as np
from scipy import stats
from math import isnan

# set this to localhost for now
# this is correct for son-emu started outside of a container or as a container with net=host
#TODO if prometheus sdk DB is started outside of emulator, place these globals in an external SDK config file?
prometheus_ip = 'localhost'
# When started in a docker container
#prometheus_ip = '172.17.0.1'
# when sdk is started with docker-compose, we could use
# prometheus_ip = 'prometheus'
prometheus_port = '9090'
prometheus_REST_api = 'http://{0}:{1}'.format(prometheus_ip, prometheus_port)

class Metric(object):

    def __init__(self, **definition):
        self.metric_type = None
        self.metric_name = None
        self.query = None
        self.desc = None
        self.unit = None
        self.list_values = []
        self.CI = {'max': float('nan'), 'min': float('nan')}

        self.reset()

        # populate object from definition dict (eg. from YAML)
        self.__dict__.update(definition)


    def doCalc(self):
        self.median = float(np.nanmedian(self.list_values))
        self.average = float(np.nanmean(self.list_values))
        self.mode = float(stats.mode(self.list_values, nan_policy='omit')[0])
        #self.average = self.sum / self.len

        self.CI['min'] = float(np.nanpercentile(self.list_values, 5))
        self.CI['max'] = float(np.nanpercentile(self.list_values, 95))

        # mu = self.average
        # sigma = np.nanstd(self.list_values).item()
        # N = self.len
        # if sigma > 0:
        #     R = t.interval(0.95, N - 1, loc=mu, scale=sigma / np.sqrt(N))
        #     self.CI['min'] = R[0].item()
        #     self.CI['max'] = R[1].item()


    def addValue(self, value):
        self.last_value = value

        # update running average
        self.list_values.append(value)


    def reset(self):
        # reset the measured values
        # last added value
        self.last_value = float('nan')
        # list of all values
        self.list_values = []
        # running sum of all values
        self.sum = 0
        # how many gathered values
        self.len = 0
        # running average
        self.average = float('nan')
        self.mode = float('nan')
        self.median = float('nan')

        # confidence interval
        self.CI = {'max': float('nan'), 'min': float('nan')}


# translate metric names to the prometheus query
class MetricTemplate(object):

    def __init__(self, **definition):
        self.metric_name = None
        self.query_template = None
        self.unit = None
        self.desc = None
        # populate object from definition dict (eg. from YAML)
        self.__dict__.update(definition)

# import all prometheus metrics from yml file
src_path = os.path.join('prometheus', 'prometheus_queries.yml')
srcfile = pkg_resources.resource_filename(__name__, src_path)
prometheus_metrics = read_yaml(srcfile)

# All metric types in the prometheus config file
nsdlink_metrics = ['packet_rate', 'byte_rate', 'packet_count', 'byte_count',
                   'packet_rate_cadv', 'byte_rate_cadv', 'packet_count_cadv', 'byte_count_cadv', 'packet_size_cadv']
network_metrics = ['packet_rate', 'byte_rate', 'packet_count', 'byte_count',
                   'packet_rate_cadv', 'bitrate_cadv', 'packet_count_cadv', 'byte_count_cadv', 'packet_size_cadv']
#testvnf_metrics = ['packet_loss', 'jitter', 'throughput']
testvnf_metrics = []
compute_metrics = []
#compute_metrics = ['cpu', 'mem', 'disk', 'host_cpu', 'tcp_established_cadv', 'tasks_uninterruptible_cadv']

metric2flowquery = {}
for metric in prometheus_metrics['flowquery']:
    metric2flowquery[metric['metric_name']] = MetricTemplate(**metric)

compute2vnfquery = {}
for metric in prometheus_metrics['computequery']:
    compute2vnfquery[metric['metric_name']] = MetricTemplate(**metric)
    compute_metrics.append(metric['metric_name'])

network2vnfquery = {}
for metric in prometheus_metrics['networkquery']:
    network2vnfquery[metric['metric_name']] = MetricTemplate(**metric)

test2vnfquery = {}
for metric in prometheus_metrics['testvnfquery']:
    test2vnfquery[metric['metric_name']] = MetricTemplate(**metric)
    testvnf_metrics.append(metric['metric_name'])

def query_Prometheus(query):
    url = prometheus_REST_api + '/' + 'api/v1/query?query=' + query
    #logging.info('query:{0}'.format(url))
    req = requests.get(url)
    ret = req.json()
    if ret['status'] == 'success':
        try:
            result_array = ret['data'].get('result', [{'value': [0, float('NaN')]}])
            ret = result_array[0]['value']
        except:
            ret = [0, float('NaN')]
    else:
        ret = ret
    #logging.info('return:{0}'.format(ret))
    return ret
