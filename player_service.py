"""HTTP service the Lean Poker dealer calls (POST action=bet_request|showdown|version|check).
Threaded, because several games run at once; always answers 200 so a crash can't get us banned."""
import time
import json
import urllib.parse
import http.server
import os
import sys
import traceback
from player import Player


HOST_NAME = '0.0.0.0'
PORT_NUMBER = 'PORT' in os.environ and int(os.environ['PORT']) or 9000


class PlayerService(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def do_POST(self):
        response = b''
        action = ''
        try:
            length = int(self.headers.get('content-length') or 0)
            qs = self.rfile.read(length).decode()
            postvars = urllib.parse.parse_qs(qs, keep_blank_values=1)
            action = postvars.get('action', [''])[0]
            game_state = json.loads(postvars['game_state'][0]) if 'game_state' in postvars else {}

            if action == 'bet_request':
                response = b'%d' % Player().betRequest(game_state)
            elif action == 'showdown':
                Player().showdown(game_state)
            elif action == 'version':
                response = Player.VERSION.encode()
        except Exception:
            sys.stderr.write('WARN service error: %s\n' % traceback.format_exc())
            if action == 'bet_request':
                response = b'0'

        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(response)


if __name__ == '__main__':
    server_class = http.server.ThreadingHTTPServer
    httpd = server_class((HOST_NAME, PORT_NUMBER), PlayerService)
    print((time.asctime(), "Server Starts - %s:%s" % (HOST_NAME, PORT_NUMBER)))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    httpd.server_close()
    print((time.asctime(), "Server Stops - %s:%s" % (HOST_NAME, PORT_NUMBER)))
