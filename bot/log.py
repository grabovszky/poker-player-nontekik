"""One compact JSON line per decision to stderr (shows up in the production log view)."""
import json
import sys
import traceback


def decision(d):
    try:
        sys.stderr.write(json.dumps(d, separators=(',', ':')) + '\n')
        sys.stderr.flush()
    except Exception:
        pass


def warn(msg, game_id=None):
    try:
        sys.stderr.write(json.dumps({'level': 'WARN', 'msg': msg, 'game_id': game_id,
                                     'trace': traceback.format_exc()}, separators=(',', ':')) + '\n')
        sys.stderr.flush()
    except Exception:
        pass
