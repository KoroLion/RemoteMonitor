from paramiko import SSHClient, AutoAddPolicy
import time
import json
from http.server import HTTPServer, BaseHTTPRequestHandler, HTTPStatus
from threading import Thread

VERSION = '0.2.1'
# todo: refactor main.py
# todo: nginx or other secure http server
# todo: statistics export txt


def interface_to_dict(name, verbose, interface_data):
    interface = list(map(int, interface_data.split()))

    return {
        'name': name,
        'verbose': verbose,
        'receive': {
            'bytes': interface[0],
            'packets': interface[1],
            'errors': interface[2],
            'drop': interface[3],
            'usage': 0
        },
        'transmit': {
            'bytes': interface[8],
            'packets': interface[9],
            'errors': interface[10],
            'drop': interface[11],
            'usage': 0
        }
    }


def swap_transmit_receive(interface_data: dict):
    temp = interface_data['receive']
    interface_data['receive'] = interface_data['transmit']
    interface_data['transmit'] = temp


def get_router_data(ssh_client):

    uptime = ssh_client.exec_command('cat /proc/uptime')[1].readlines()[0]
    uptime = uptime[0:len(uptime) - 1]  # remove /n
    uptime = list(map(float, uptime.split()))

    loadavg = ssh_client.exec_command('cat /proc/loadavg')[1].readlines()[0]
    loadavg = loadavg[0:len(loadavg) - 1]  # remove /n
    loadavg = loadavg.split()
    average_load = list(map(float, loadavg[0:3]))
    processes = loadavg[3].split('/')[1]

    meminfo = ssh_client.exec_command('cat /proc/meminfo')[1].readlines()
    mem_total = int(meminfo[0].split()[1])
    mem_available = int(meminfo[1].split()[1])

    net_dev = ssh_client.exec_command('cat /proc/net/dev')[1].readlines()
    net_dev_str = str().join(net_dev)

    net_dev_str = list(map(str.lstrip, net_dev_str.split('\n')))[2:]

    s_interfaces = settings['interfaces']
    interfaces = []
    for interface in net_dev_str:
        if len(interface) > 0:
            interface_name, interface_data = interface.split(':')
            if interface_name in s_interfaces.keys():
                s_interface = s_interfaces[interface_name]
                # receive / transmit data
                interface_data = interface_to_dict(interface_name, s_interface['verbose'], interface_data)

                # swap TX and RX because of router logic (wan -> router -> computer)
                if s_interface['reverse']:
                    swap_transmit_receive(interface_data)

                interfaces.append(interface_data)

    return {
        'timestamp': time.time(),
        'uptime': {
            'up': uptime[0],
            'idle': uptime[1]
        },
        'mem': {  # in KB
            'total': mem_total,
            'available': mem_available
        },
        'average_load': {
            'min1': average_load[0],
            'min5': average_load[1],
            'min15': average_load[2]
        },
        'processes': processes,
        'interfaces': interfaces
    }


def set_usage(data: dict, prev_data: dict):
    for i in range(0, len(data['interfaces'])):
        ndata = data['interfaces'][i]
        ndata['receive']['usage'] = ndata['receive']['bytes'] - prev_data['interfaces'][i]['receive']['bytes']
        ndata['transmit']['usage'] = ndata['transmit']['bytes'] - prev_data['interfaces'][i]['transmit']['bytes']


def data_getter():
    global data

    while True:
        prev_data = data
        data = get_router_data(client)
        set_usage(data, prev_data)

        time.sleep(1)


class BaseHandler(BaseHTTPRequestHandler):
    def __init__(self, *args):
        super().__init__(*args)

    def do_GET(self):
        global data

        self.get_called = True

        if self.path == '/':
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            html_output = html.replace('{{version}}', VERSION)
            self.wfile.write(html_output.encode('utf8'))
        elif self.path == '/json_data/' or self.path == '/json_data':
            self.send_response(HTTPStatus.OK)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(data).encode('utf8'))
        else:
            self.send_response(HTTPStatus.NOT_FOUND)
            self.send_header('Content-Type', 'text/html')
            self.end_headers()
            self.wfile.write(b'<html><head><title>Not found!</title></head><body><h1>Not found!</h1></body></html>')


def run(bind='', port=8000, server_class=HTTPServer, handler_class=BaseHandler):
    server_address = (bind, port)
    httpd = server_class(server_address, handler_class)
    print('Web server started at {}:{}'.format(bind, port))
    httpd.serve_forever()


settings = {}
try:
    settings_file = open('settings.json', 'r')
    settings = json.loads(str().join(settings_file.readlines()))
    settings_file.close()
except FileNotFoundError:
    print('settings.json not found, creating... Please fill it with your settings.')
    template_file = open('settings.template.json', 'r')
    settings_file = open('settings.json', 'w')
    settings_file.writelines(template_file.readlines())
    template_file.close()
    settings_file.close()

if len(settings.keys()) > 0 and settings.get('webServer', None):
    client = SSHClient()
    client.set_missing_host_key_policy(AutoAddPolicy())
    router_settings = settings['router']
    client.connect(
        hostname=router_settings['host'],
        port=router_settings['port'],
        username=router_settings['username'],
        password=router_settings['password']
    )

    data = get_router_data(client)
    with open('index.html') as index:
        html = str().join(index.readlines())

    print('Starting...')
    t = Thread(target=data_getter)
    t.start()
    run(settings['webServer']['bind'], settings['webServer']['port'])

    client.close()
else:
    print('Invalid settings!')
