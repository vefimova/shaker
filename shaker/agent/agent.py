# Copyright (c) 2015 Mirantis Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import re
import shlex
import tempfile
import time
import uuid

from oslo_concurrency import processutils
from oslo_config import cfg
from oslo_log import log as logging
import psutil
import sys
import zmq

from shaker.engine import config
from shaker.engine import utils


LOG = logging.getLogger(__name__)


def poll_task(socket, agent_id):
    payload = {
        'operation': 'poll',
        'agent_id': agent_id,
    }
    LOG.debug('Polling task: %s', payload)
    socket.send_json(payload)
    res = socket.recv_json()
    LOG.debug('Received: %s', res)
    return res


def send_reply(socket, agent_id, result):
    message = {
        'operation': 'reply',
        'agent_id': agent_id,
    }
    message.update(result)

    LOG.debug('Sending reply: %s', message)
    socket.send_json(message)
    res = socket.recv_json()
    LOG.debug('Received: %s', res)
    return res


def run_command(command):
    command_stdout, command_stderr = None, None

    if command['type'] == 'program':
        command_stdout, command_stderr = processutils.execute(
            *shlex.split(command['data']), check_exit_code=False)

    elif command['type'] == 'script':
        fd = tempfile.mkstemp()
        os.write(fd[0], command['data'])
        os.close(fd[0])
        LOG.debug('stored script into %s', fd[1])
        command_stdout, command_stderr = processutils.execute(
            *shlex.split('bash %s' % fd[1]), check_exit_code=False)

    else:
        command_stderr = 'Unknown command type : %s' % command['type']

    return dict(stdout=command_stdout, stderr=command_stderr)


def work(agent_id, endpoint, polling_interval):
    LOG.info('Agent id is: %s', agent_id)
    LOG.info('Connecting to server: %s', endpoint)

    context = zmq.Context()
    socket = context.socket(zmq.REQ)
    socket.connect('tcp://%s' % endpoint)

    try:
        while True:
            task = poll_task(socket, agent_id)

            if task['operation'] == 'execute':
                now = int(time.time())
                start_at = task.get('start_at') or now
                command = task.get('command')
                LOG.debug('Scheduling command %s at %s', command, start_at)

                time.sleep(start_at - now)

                result = run_command(command)
                send_reply(socket, agent_id, result)

            elif task['operation'] == 'configure':
                if 'polling_interval' in task:
                    polling_interval = task.get('polling_interval')
                    send_reply(socket, agent_id, {})

            time.sleep(polling_interval)

    except BaseException as e:
        if isinstance(e, KeyboardInterrupt):
            LOG.info('The process is interrupted')
            sys.exit(3)
        else:
            LOG.exception(e)


def get_mac():
    s = '%012x' % uuid.getnode()
    return ':'.join([s[i:i + 2] for i in range(0, len(s), 2)])


def check_if_already_running(my_endpoint):
    def _pick_shaker_agents():
        PSUTIL2 = psutil.version_info >= (2, 0)  # compatibility bw 1.x and 2.x

        my_pid = os.getpid()
        for pid in psutil.get_pid_list():
            if pid != my_pid:
                try:
                    p = psutil.Process(pid)
                except Exception as e:
                    LOG.info('Exception while iterating process list: %s', e)

                name = p.name() if PSUTIL2 else p.name
                if name == 'shaker-agent':
                    yield (p.cmdline() if PSUTIL2 else p.cmdline)

    for cmdline in _pick_shaker_agents():
        LOG.info('Found running shaker-agent: %s', ' '.join(cmdline))

        args = iter(cmdline)
        for arg in args:
            if arg == '--server-endpoint':
                other_endpoint = next(args)
                return other_endpoint == my_endpoint

    return None


def main():
    utils.init_config_and_logging(config.COMMON_OPTS + config.AGENT_OPTS)

    endpoint = cfg.CONF.server_endpoint
    polling_interval = cfg.CONF.polling_interval
    agent_id = cfg.CONF.agent_id

    if not re.match('\S+:\d+', endpoint):
        LOG.error('Wrong value of server_endpoint, expected <host>:<port>, '
                  'but got: %s', endpoint)
        exit(1)

    if check_if_already_running(endpoint):
        LOG.warning('Shaker-agent already running with the same endpoint')
        exit(1)

    if not agent_id:
        agent_id = get_mac()
        LOG.info('Using MAC address as agent_id: %s', agent_id)

    work(agent_id, endpoint, polling_interval)

if __name__ == "__main__":
    main()
