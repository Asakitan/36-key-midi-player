#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
排行榜服务端 — 默认本地部署在 127.0.0.1:9998

功能:
  • POST /api/upload      — 接收加密的玩家统计数据
  • POST /api/leaderboard — 返回加密的排行榜数据
  • 数据存储: JSON 文件 (轻量, 无需数据库)
  • 加密: AES-256-CBC + HMAC-SHA256 (与客户端一致)
  • 最小化流量: 仅加密 payload, 无冗余字段

部署 (推荐使用 screen/systemd):
  pip install flask
  python leaderboard_server.py

或使用 gunicorn:
  pip install flask gunicorn
  gunicorn -b 0.0.0.0:9998 -w 2 leaderboard_server:app
"""

import os
import sys
import json
import time
import hashlib
import hmac
import base64
import secrets
import threading
from datetime import datetime

# ═══════════════════════════════════════════════
#  Flask / 降级 http.server
# ═══════════════════════════════════════════════

try:
    from flask import Flask, request, jsonify
    USE_FLASK = True
except ImportError:
    USE_FLASK = False

# ═══════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════

PORT = 9998
_BASE_DIR = (os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
             else os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(_BASE_DIR, 'lb_data')
DATA_FILE = os.path.join(DATA_DIR, 'players.json')
LOG_FILE = os.path.join(DATA_DIR, 'server.log')

# 共享密钥 (必须与客户端 leaderboard.py 一致!)
_SHARED_SECRET = b'SaoMidiPlayer_Leaderboard_2024_v1'

# 速率限制: 每 IP 每分钟最多 20 请求
_RATE_LIMIT = 20
_RATE_WINDOW = 60
_rate_map = {}  # ip -> [timestamps]
_rate_lock = threading.Lock()

os.makedirs(DATA_DIR, exist_ok=True)


# ═══════════════════════════════════════════════
#  加密工具 (与 leaderboard.py 完全一致)
# ═══════════════════════════════════════════════

def _derive_key(salt: bytes) -> bytes:
    return hashlib.pbkdf2_hmac('sha256', _SHARED_SECRET, salt, 100_000, dklen=32)


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    klen = len(key)
    return bytes(b ^ key[i % klen] for i, b in enumerate(data))


def _aes_cbc_encrypt(plaintext: bytes, key: bytes) -> tuple:
    iv = secrets.token_bytes(16)
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding as sym_padding
        padder = sym_padding.PKCS7(128).padder()
        padded = padder.update(plaintext) + padder.finalize()
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        enc = cipher.encryptor()
        ct = enc.update(padded) + enc.finalize()
        return iv, ct
    except ImportError:
        pass
    stream_key = hashlib.sha256(key + iv).digest() * ((len(plaintext) // 32) + 2)
    ct = _xor_bytes(plaintext, stream_key[:len(plaintext)])
    return iv, ct


def _aes_cbc_decrypt(iv: bytes, ciphertext: bytes, key: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.primitives import padding as sym_padding
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
        dec = cipher.decryptor()
        padded = dec.update(ciphertext) + dec.finalize()
        unpadder = sym_padding.PKCS7(128).unpadder()
        return unpadder.update(padded) + unpadder.finalize()
    except ImportError:
        pass
    stream_key = hashlib.sha256(key + iv).digest() * ((len(ciphertext) // 32) + 2)
    return _xor_bytes(ciphertext, stream_key[:len(ciphertext)])


def decrypt_payload(b64_data: str) -> dict:
    raw = base64.b64decode(b64_data)
    salt = raw[:16]
    iv = raw[16:32]
    sig = raw[32:64]
    ct = raw[64:]
    key = _derive_key(salt)
    expected_sig = hmac.new(key, iv + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError('signature mismatch')
    plaintext = _aes_cbc_decrypt(iv, ct, key)
    return json.loads(plaintext.decode('utf-8'))


def encrypt_payload(data: dict) -> str:
    plaintext = json.dumps(data, ensure_ascii=False).encode('utf-8')
    salt = secrets.token_bytes(16)
    key = _derive_key(salt)
    iv, ct = _aes_cbc_encrypt(plaintext, key)
    sig = hmac.new(key, iv + ct, hashlib.sha256).digest()
    packet = salt + iv + sig + ct
    return base64.b64encode(packet).decode('ascii')


# ═══════════════════════════════════════════════
#  数据存储 (线程安全 JSON 文件)
# ═══════════════════════════════════════════════

_data_lock = threading.Lock()


def _sanitize_device_name(name: str) -> str:
    raw = (name or '').strip()
    safe = ''.join(ch for ch in raw if ch.isalnum() or ch in ' -_#@.[]()（）【】')
    safe = safe.strip(' -_')
    return (safe or 'Local Device')[:32]


def _load_data() -> dict:
    """加载玩家数据 {device_id: {username, level, xp, ...}}."""
    with _data_lock:
        try:
            if os.path.exists(DATA_FILE):
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
    return {}


def _save_data(data: dict):
    with _data_lock:
        try:
            tmp = DATA_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, DATA_FILE)
        except Exception as e:
            _log(f'save error: {e}')


def _log(msg: str):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    line = f'[{ts}] {msg}'
    print(line)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


# ═══════════════════════════════════════════════
#  速率限制
# ═══════════════════════════════════════════════

def _check_rate(ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        if ip not in _rate_map:
            _rate_map[ip] = []
        _rate_map[ip] = [t for t in _rate_map[ip] if now - t < _RATE_WINDOW]
        if len(_rate_map[ip]) >= _RATE_LIMIT:
            return False
        _rate_map[ip].append(now)
    return True


# ═══════════════════════════════════════════════
#  请求处理
# ═══════════════════════════════════════════════

def handle_upload(payload: dict) -> dict:
    """处理上传请求."""
    device_id = payload.get('device_id', '')
    if not device_id or len(device_id) > 64:
        return {'error': 'invalid device_id'}

    username = str(payload.get('username', 'Player'))[:32]
    player_id = _sanitize_device_name(payload.get('player_id', '') or username or payload.get('device_name', '') or 'Player')
    level = min(9999, max(1, int(payload.get('level', 1))))
    xp = min(99999999, max(0, int(payload.get('xp', 0))))
    songs_played = min(999999, max(0, int(payload.get('songs_played', 0))))
    play_time = min(9999999, max(0, float(payload.get('play_time', 0))))
    profession = str(payload.get('profession', ''))[:32]

    data = _load_data()
    data[device_id] = {
        'username': username,
        'device_name': player_id,
        'player_id': player_id,
        'level': level,
        'xp': xp,
        'songs_played': songs_played,
        'play_time': round(play_time, 1),
        'profession': profession,
        'last_seen': int(time.time()),
    }
    _save_data(data)
    _log(f'upload: {player_id} Lv.{level} XP:{xp} songs:{songs_played}')
    return {'ok': True}


def handle_leaderboard(payload: dict) -> dict:
    """处理排行榜拉取请求."""
    sort_by = payload.get('sort_by', 'xp')
    limit = min(100, max(1, int(payload.get('limit', 50))))

    if sort_by not in ('xp', 'level', 'songs_played', 'play_time'):
        sort_by = 'xp'

    data = _load_data()
    entries = []
    for device_id, entry in data.items():
        row = dict(entry or {})
        row['device_id'] = device_id
        row['player_id'] = _sanitize_device_name(
            row.get('player_id', '') or row.get('username', '') or row.get('device_name', '') or 'Player'
        )
        row['device_name'] = row['player_id']
        entries.append(row)

    # 排序
    entries.sort(key=lambda e: e.get(sort_by, 0), reverse=True)
    entries = entries[:limit]

    # 添加排名
    result = []
    for i, e in enumerate(entries):
        result.append({
            'rank': i + 1,
            'device_id': e.get('device_id', ''),
            'device_name': e.get('device_name', ''),
            'player_id': e.get('player_id', ''),
            'username': e.get('username', 'Player'),
            'level': e.get('level', 1),
            'xp': e.get('xp', 0),
            'songs_played': e.get('songs_played', 0),
            'play_time': round(e.get('play_time', 0), 1),
            'profession': e.get('profession', ''),
        })

    return {'leaderboard': result}


# ═══════════════════════════════════════════════
#  Flask 路由
# ═══════════════════════════════════════════════

if USE_FLASK:
    app = Flask(__name__)

    @app.route('/api/upload', methods=['POST'])
    def api_upload():
        ip = request.remote_addr
        if not _check_rate(ip):
            return jsonify({'error': 'rate limited'}), 429
        try:
            body = request.get_json(force=True)
            payload = decrypt_payload(body.get('data', ''))
            if payload.get('action') != 'upload':
                return jsonify({'error': 'invalid action'}), 400
            result = handle_upload(payload)
            return jsonify(result), 200
        except Exception as e:
            _log(f'upload error from {ip}: {e}')
            return jsonify({'error': 'bad request'}), 400

    @app.route('/api/leaderboard', methods=['POST'])
    def api_leaderboard():
        ip = request.remote_addr
        if not _check_rate(ip):
            return jsonify({'error': 'rate limited'}), 429
        try:
            body = request.get_json(force=True)
            payload = decrypt_payload(body.get('data', ''))
            if payload.get('action') != 'fetch':
                return jsonify({'error': 'invalid action'}), 400
            result = handle_leaderboard(payload)
            encrypted = encrypt_payload(result)
            return jsonify({'data': encrypted}), 200
        except Exception as e:
            _log(f'leaderboard error from {ip}: {e}')
            return jsonify({'error': 'bad request'}), 400

    @app.route('/health', methods=['GET'])
    def health():
        data = _load_data()
        return jsonify({
            'status': 'ok',
            'players': len(data),
            'uptime': int(time.time() - _start_time),
        })

else:
    # ── 纯标准库 fallback (http.server) ──
    from http.server import HTTPServer, BaseHTTPRequestHandler

    class LeaderboardHandler(BaseHTTPRequestHandler):
        def do_POST(self):
            ip = self.client_address[0]
            if not _check_rate(ip):
                self._send_json({'error': 'rate limited'}, 429)
                return

            try:
                length = int(self.headers.get('Content-Length', 0))
                raw = self.rfile.read(length)
                body = json.loads(raw.decode('utf-8'))
                payload = decrypt_payload(body.get('data', ''))
            except Exception as e:
                _log(f'decrypt error from {ip}: {e}')
                self._send_json({'error': 'bad request'}, 400)
                return

            if self.path == '/api/upload':
                if payload.get('action') != 'upload':
                    self._send_json({'error': 'invalid action'}, 400)
                    return
                result = handle_upload(payload)
                self._send_json(result)
            elif self.path == '/api/leaderboard':
                if payload.get('action') != 'fetch':
                    self._send_json({'error': 'invalid action'}, 400)
                    return
                result = handle_leaderboard(payload)
                encrypted = encrypt_payload(result)
                self._send_json({'data': encrypted})
            else:
                self._send_json({'error': 'not found'}, 404)

        def do_GET(self):
            if self.path == '/health':
                data = _load_data()
                self._send_json({
                    'status': 'ok',
                    'players': len(data),
                    'uptime': int(time.time() - _start_time),
                })
            else:
                self._send_json({'error': 'not found'}, 404)

        def _send_json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt, *args):
            _log(f'{self.client_address[0]} - {fmt % args}')


# ═══════════════════════════════════════════════
#  启动
# ═══════════════════════════════════════════════

_start_time = time.time()

if __name__ == '__main__':
    _log(f'=== Leaderboard Server starting on port {PORT} ===')
    _log(f'Data dir: {DATA_DIR}')
    _log(f'Using Flask: {USE_FLASK}')

    data = _load_data()
    _log(f'Loaded {len(data)} players')

    if USE_FLASK:
        app.run(host='0.0.0.0', port=PORT, debug=False)
    else:
        server = HTTPServer(('0.0.0.0', PORT), LeaderboardHandler)
        _log(f'Listening on 0.0.0.0:{PORT} (stdlib http.server)')
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            _log('Server stopped')
            server.server_close()
