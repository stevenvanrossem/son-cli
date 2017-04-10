"""
Copyright (c) 2015 SONATA-NFV and Paderborn University
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

"""
import paramiko
import json
import logging
import requests
import time
import threading
import yaml
import os
import stat
import argparse

# define some constants for easy changing
# will likely be removed as default values dont make sense past testing
PATH_COMMAND = "cd ~/son-emu"
EXEC_COMMAND = "sudo python src/emuvim/examples/profiling.py"

# create a Logger
logging.basicConfig()
LOG = logging.getLogger("SON-Profile Emulator")
LOG.setLevel(logging.DEBUG)
logging.getLogger("werkzeug").setLevel(logging.WARNING)

"""
 A class which provides methods to do experiments with service packages
"""
class Emulator:

    """
     Initialize with a list of descriptors of workers to run experiments on
     :tpd: target platforms descriptor. A dictionary describing the remote hosts on which service can be tested or a dictionary containing a key which value is the descriptor
     :remote_logging: Set it to True if logs of the remote topology should be shown in the local log files.
        WARNING: They will be shown at the end of each experiment, will not neccessarily be complete and are output as logging error, probably because of mininet
    """
    def __init__(self, tpd, remote_logging=False):
        # if the whole config dictionary has been given, extract only the target platforms
        # a descriptor version should only be in the top level of the file
        if "descriptor_version" in tpd:
            tpd = tpd.get("target_platforms")
            LOG.debug("Found target platforms in dictionary.")

        # save the emulator nodes
        self.emulator_nodes = tpd

        # check for empty emulator node lists
        if not len(self.emulator_nodes):
            LOG.error("No remote hosts specified.")
            raise Exception("Need at least one emulator to be specified in the target platforms descriptor.")

        # all nodes are available at the start
        self.available_nodes = self.emulator_nodes.keys()
        LOG.info("%r nodes found."%len(self.emulator_nodes))
        LOG.debug("List of emulator nodes: %r"%self.emulator_nodes.keys())

        # save the remote_logging flag
        if remote_logging:
            LOG.info("Remote logs will be shown.")
        else:
            LOG.info("Remote logs will not be shown.")
        self.remote_logging = remote_logging

    """
     Conduct multiple experiments using the do_experiment method
     All experiments are started in a separate thread
     The order in which the experiments are run is not fixed!
     :experiments: a dictionary mapping from run_id to package path
     :runtime: the time an experiment runs for
    """
    def do_experiment_series(self, experiments, runtime=10):
        # start the experiments in separate threads
        LOG.info("%r experiments will be run."%len(experiments.keys()))
        LOG.info("Runtime for each experiment is %r seconds."%runtime)
        for i in experiments.keys():
            t = threading.Thread(target=self.do_experiment, kwargs={"run_id":i, "path_to_pkg":experiments[i], "runtime":runtime})
            t.start()

    """
     Conduct a single experiment with given values
     One experiment consists of:
     1) starting the topology remotely on a server
     2) uploading the service package
     3) starting the service
     4) wait a specified amount of time
     5) stop the service
     6) gather results
     7) clean up results from remote server
     8) close the connection
     :path_to_pkg: the path to the service package which is to be tested
     :run_id: the experiment ID for this run. Files generated by the service workers will be found under result/run_id
     :runtime: the service will run for the specified amount of seconds
     :node_name: the name of the emulator node to be used for the experiment. If not specified, the first available node will be used.
    """
    def do_experiment(self,
            path_to_pkg,
            run_id,
            runtime=10,
            node_name=None):
        # if the package path contains a tilde, expand it to full directory path
        path_to_pkg = os.path.expanduser(path_to_pkg)
        LOG.debug("Run %r: Path to package for %r"%(run_id, path_to_pkg))

        # determine which worker to use (specified or first available)
        if not node_name:
            LOG.debug("Run %r: No node name specified. Choosing first available Node."%run_id)
            # choose an emulator node
            # the first idle node would be best
            while not self.available_nodes:
                time.sleep(1)
            node_name = self.available_nodes.pop()
        LOG.debug("Run %r: Node name for this experiment is %s"%(run_id, node_name))
        # check whether the specified worker exists
        if not node_name in self.emulator_nodes:
            LOG.critical("Run %r: Specified node does not exist."%run_id)
            raise Exception("The specified node does not exist.")
        node=self.emulator_nodes[node_name]

        # get neccessary information from (un-)specified worker
        LOG.info("Run %r: Running package for %r seconds on emulator node %r."%(run_id, runtime, node_name))
        address = node["address"]
        LOG.debug("Run %r: Remote address is %r."%(run_id, address))
        # get the port to upload the packages to, if not specified, default to 5000
        package_port = node.get("package_port", 5000)
        LOG.debug("Run %r: Port for packages is %r."%(run_id, package_port))
        # get the ssh port, if not specified, default to 22
        ssh_port = node.get("ssh_port", 22)
        LOG.debug("Run %r: SSH port is %r."%(run_id, ssh_port))
        username = node["ssh_user"]
        LOG.debug("Run %r: Username for ssh connection is %r."%(run_id, username))
        key_loc = os.path.expanduser(node["ssh_key_loc"])
        LOG.debug("Run %r: Location of ssh key is %r."%(run_id, key_loc))

        # connect to the client per ssh
        ssh = paramiko.client.SSHClient()

        # set policy for unknown hosts or import the keys
        # for now, we just add all new keys instead of adding certain ones
        ssh.set_missing_host_key_policy(paramiko.client.AutoAddPolicy())

        # import the RSA key
        pkey = paramiko.RSAKey.from_private_key_file(key_loc)

        # connect to the remote host via ssh
        ssh.connect(address, port=ssh_port, username=username, pkey=pkey)
        LOG.info("Run %r: Connected to remote host."%run_id)

        # start the profiling topology on the client
        # use a seperate thread to prevent blocking by the topology
        LOG.info("Run %r: Starting remote topology."%run_id)
        comm = threading.Thread(target=self._exec_command, args=(ssh, "%s;%s -p %s"%(PATH_COMMAND,EXEC_COMMAND,package_port)))
        comm.start()

        # wait a short while to let the topology start
        time.sleep(5)

        # upload the service package
        LOG.info("Run %r: Path to package is %r" % (run_id, path_to_pkg))
        f = open(path_to_pkg, "rb")
        LOG.info("Run %r: Uploading package to http://%r." % (run_id, address))
        r1 = requests.post("http://%s:%s/packages"%(address,package_port), files={"package":f})
        service_uuid = json.loads(r1.text).get("service_uuid")
        LOG.debug("Run %r: Service uuid is %s"%(run_id, service_uuid))

        # start the service
        r2 = requests.post("http://%s:%s/instantiations"%(address,package_port), data=json.dumps({"service_uuid":service_uuid}))
        service_instance_uuid = json.loads(r2.text).get("service_instance_uuid")
        LOG.debug("Run %r: Service instance uuid is %s"%(run_id, service_instance_uuid))

        # let the service run for a specified time
        LOG.info("Run %r: Sleep for %r seconds." % (run_id, runtime))
        time.sleep(runtime)

        # stop the service
        LOG.info("Run %r: Stopping service"%run_id)
        requests.delete("http://%s:%s/instantiations"%(address,package_port), data=json.dumps({"service_uuid":service_uuid, "service_instance_uuid":service_instance_uuid}))

        # stop the remote topology
        LOG.info("Run %r: Stopping remote topology."%run_id)
        self._exec_command(ssh, 'sudo pkill -f "%s -p %s"'%(EXEC_COMMAND, package_port))

        # gather the results etc.
        sftp = ssh.open_sftp()
        # switch to directory containing relevant files
        sftp.chdir("/tmp/results/%s/"%service_uuid)
        # the path to which the files will be copied
        local_path = "result/%r"%run_id

        # all files in the folder have to be copied, directories have to be handled differently
        files_to_copy = sftp.listdir()
        # as long as there are files to copy
        LOG.info("Run %r: Copying results from remote hosts."%run_id)
        while files_to_copy:
            # get next "file"
            file_path = files_to_copy.pop()
            # if the "file" is a directory, put all files contained in the directory in the list of files to be copied
            file_mode = sftp.stat(file_path).st_mode
            if stat.S_ISDIR(file_mode):
                LOG.debug("Run %r: Found directory %s"%(run_id, file_path))
                more_files = sftp.listdir(path=file_path)
                for f in more_files:
                    # we need the full path
                    files_to_copy.append(os.path.join(file_path,f))
                os.makedirs(os.path.join(local_path, file_path))
            elif stat.S_ISREG(file_mode):
                # the "file" is an actual file
                LOG.debug("Run %r: Found file %s"%(run_id, file_path))
                # copy the file to the local system, preserving the folder hierarchy
                sftp.get(file_path, os.path.join(local_path,file_path))
            else:
                # neither file nor directory
                # skip it
                LOG.debug("Run %r: Skipping %s: Neither file nor directory"%(run_id, file_path))

        # remove all temporary files and directories from the remote host
        LOG.info("Run %r: Removing results on remote host."%run_id)
        self._exec_command(ssh, "sudo rm -r /tmp/results/%s"%service_uuid)

        LOG.info("Run %r: Closing connections."%run_id)
        # close the sftp connection
        sftp.close()

        # close the ssh connection
        ssh.close()

        # make the current worker available again
        self.available_nodes.append(node_name)

    """
    Helper method to be called in a thread
    A single command is executed on a remote server via ssh
    """
    def _exec_command(self, ssh, command):
        comm_in, comm_out, comm_err = ssh.exec_command(command)
        comm_in.close()
        while not (comm_out.channel.exit_status_ready() and comm_err.channel.exit_status_ready()):
            for line in comm_out.read().splitlines():
                if self.remote_logging:
                    LOG.debug(line)
            for line in comm_err.read().splitlines():
                if self.remote_logging:
                    LOG.error(line)

"""
 Checks whether the given file path is an existing config file
"""
def config_file_exists(file_path):
    if not os.path.exists(file_path):
        raise argparse.ArgumentError("%r needs to be an existing file."%file_path)
    with open(file_path, "r") as f:
        config_dict = yaml.load(f)
        if not "target_platforms" in config_dict:
            raise argparse.ArgumentError("%r does not contain a target platforms descriptor."%file_path)
    f.close()
    return file_path

"""
 Checks whether the given file_path if an existing file
"""
def package_file_exists(file_path):
    if not os.path.exists(file_path):
        raise argparse.ArgumentError("%r needs to be an existing file."%file_path)
    return file_path

if __name__=='__main__':
    parser = argparse.ArgumentParser(description="Run experiments with the given son packages")
    parser.add_argument("--time", "-t",
            help="The runtime of every experiment",
            type=int, default=10, required=False, dest="time", metavar="seconds")
    parser.add_argument("--remote-logging",
            help="Enable showing logs of remote topology",
            action="store_true", required=False, dest="rem_log")
    parser.add_argument("--config-file", "-c",
            help="Specify which config file to use for specification of remote hosts",
            required=False, dest="config", type=config_file_exists, metavar="Config Path")
    parser.add_argument("package_path",
            help="Path to a package",
            nargs="+", type=package_file_exists, metavar="Package Path")
    args = parser.parse_args()

    config_path = args.config
    if not config_path:
        config_path = "src/son/profile/config.yml"
    with open(config_path, "r") as tpd:
        conf = yaml.load(tpd)
    tpd.close()
    remote_logging = args.rem_log
    e = Emulator(tpd=conf, remote_logging=remote_logging)
    experiments = {i: args.package_path[i] for i in range(len(args.package_path))}
    e.do_experiment_series(experiments, runtime=args.time)
