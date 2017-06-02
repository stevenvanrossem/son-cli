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

import logging
from requests import Session, post
import websocket
import threading
from subprocess import call
import json
from son.profile.helper import read_yaml, write_yaml
from prometheus_client import start_http_server, Gauge

"""
This class implements the son-sp commands.
These commands translate to the API's of the SONATA SP
"""

LOG = logging.getLogger('SP_monitor')
LOG.setLevel(level=logging.INFO)

prometheus_stream_port = 8082
prometheus_server_api = 'http://127.0.0.1:9090'
prometheus_config_path = '/tmp/son-monitor/prometheus/prometheus_sdk.yml'

class Service_Platform():
    def __init__(self, monitor_api=None, export_port=8082, **kwargs):
        self.monitor_api = monitor_api
        # Build up our session
        self.session = Session()
        self.session.headers = {
            "Accept": "application/json; charset=UTF-8"
        }

        global prometheus_stream_port
        prometheus_stream_port = export_port

        global prometheus_server_api
        prometheus_server_api = kwargs.get('prometheus_server_api', prometheus_server_api)
        global prometheus_config_path
        prometheus_config_path = kwargs.get('prometheus_config_path', prometheus_config_path)

        self.ws_thread = None
        # websocket in the SP
        self.ws = None


    def list(self, **kwargs):
        # if metric is specified, show the list of VNFs that export ths metric
        metric = kwargs.get('metric')
        if metric :
            url = self.monitor_api + 'prometheus/metrics/name/' + metric
            ret = self.session.get(url).json().get("metrics").get("result")
        else:
            url = self.monitor_api + 'prometheus/metrics/list'
            resp = self.session.get(url)
            ret = resp.json().get('metrics')

        return ret

    def stream(self, **kwargs):
        metric = kwargs.get('metric')
        vnf_name = kwargs.get('vnf_name')

        action = kwargs.get('action', 'start')
        if action == 'stop':
            SP_websocket._config_prometheus(remove=True)
            if self.ws:
                self.ws.close()
            #  kill all running websocket streams
            call(['pkill', '-f', 'son-monitor stream'])
            return 'websocket closed'

        # create the websocket with a filter eg: {"metric":"vm_cpu_perc","filters":["exported_instance":"vtc-vnf"]}
        url = self.monitor_api + 'ws/new'
        data = {'metric':str(metric), 'filters':str(list("exported_instance={}".format(vnf_name)))}
        response = self.session.post(url, json=data)
        code = response.status_code
        if code == 200:
            ws_url = response.json().get('ws_url')
            LOG.info('ws_url: {}'.format(ws_url))
            self.ws = SP_websocket(ws_url, vnf_name=vnf_name, metric=metric)
            self.ws_thread = threading.Thread(target=self.ws.run_forever)
            self.ws_thread.daemon = True
            self.ws_thread.start()
            self.ws_thread.join()
            return 'websocket thread started'



class SP_websocket(websocket.WebSocketApp):
    def __init__(self, url, vnf_name=None, metric=None,
                 desc='exported metric from SP', print=False):

        self.vnf_name = vnf_name
        self.metric = metric
        self.desc = desc
        self.print = print

        self.metric_received = False
        self.prometheus_metric = None

        websocket.WebSocketApp.__init__(self, url,
                                        on_message=self._on_message,
                                        on_error=self._on_error,
                                        on_close=self._on_close,
                                        on_open=self._on_open
                                        )

    def _on_message(self, ws, message):

        metric = self.find_metric(message)

        # set the metric with the correct labels, when first value is received
        if not self.metric_received:
            self.set_exported_metric(metric)

        # only export the selected metric and vnf_name
        if self.metric_received:
            self.prometheus_metric.labels(**metric['labels']).set(metric["value"])

        # some info  printing
        if self.metric_received and self.print \
                and self.vnf_name is not None and self.metric is not None:
            message = self.filter_output(message)

    def _on_error(self, ws, error):
        self._config_prometheus(remove=True)
        pass

    def _on_close(self, ws):
        self._config_prometheus(remove=True)
        pass

    def _on_open(self, ws):
        global prometheus_stream_port

        # start local http export server
        start_http_server(prometheus_stream_port)

        # make Prometheus scrape this server
        self._config_prometheus()

    @staticmethod
    def _config_prometheus(remove=False):
        global prometheus_server_api
        global prometheus_config_path
        # make Prometheus scrape this server
        config_file = read_yaml(prometheus_config_path)
        targets = config_file.get('scrape_configs', [])
        SP_stream_config = next((target for target in targets if target.get('job_name') == 'SP_stream'), None)
        # the SP http server is not yet added to the config file
        config_dict = {'job_name': 'SP_stream', 'scrape_interval': '1s',
                       'static_configs': [{'targets': ['172.17.0.1:{}'.format(prometheus_stream_port)]}]}
        if not SP_stream_config and not remove:
            config_file['scrape_configs'].append(config_dict)
            LOG.info('added SP stream to Prometheus')
        elif remove and SP_stream_config:
            config_file['scrape_configs'].remove(config_dict)
            LOG.info('removed SP stream from Prometheus')

        write_yaml(prometheus_config_path, config_file)
        post(prometheus_server_api + '/-/reload')

    def set_exported_metric(self, metric):
        if len(metric['labels']) > 0 :
            # metric is found and labels are set
            metric_name = self.metric
            labels = list(metric['labels'])
            self.prometheus_metric = Gauge(metric_name, self.desc, labels)
            self.metric_received = True
            LOG.info('exporting metric with labels: {}'.format(labels))

    def filter_output(self, message):
        data = json.loads(message)
        metric_list = data.get(self.metric, [])
        metric = {}
        for metric in metric_list:
            for label in metric.get('labels', []):
                if self.vnf_name in label:
                    LOG.info('label: {}'.format(label))
                    LOG.info('value: {}'.format(metric.get('value')))
                    LOG.info('time: {}'.format(metric.get('time')))
                    break
        return metric

    def find_metric(self, message):
        data = json.loads(message)
        metric_list = data.get(self.metric, [])
        labels = {}
        value = None
        metric_found = False
        for metric in metric_list:
            for label in metric.get('labels', []):
                key, value = label.split('=')
                labels[key] = str(value).replace('"','')
                if self.vnf_name in label:
                    metric_found = True
            if not metric_found:
                labels = {}
            else:
                # metric is found and labels are set
                value = metric.get('value')
                break

        metric = {'labels':labels, "value":value }
        return metric