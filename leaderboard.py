# -*- coding: utf-8 -*-
"""
排行榜客户端模块 — 加密通信 + 服务器交互

设计:
  • 数据加密: AES-256-CBC + HMAC-SHA256 签名 (防篡改)
  • 密钥派生: PBKDF2(shared_secret, salt) — 客户端/服务端共享
  • 通信: HTTPS POST → 47.82.157.220:9820
  • 最小化流量: 仅在用户主动打开排行榜时拉取, 播放结束后仅上传自身数据
  • 本地缓存: 上次拉取的排行榜 JSON (减少重复请求)

API:
  upload_stats()  — 上传当前玩家数据 (歌曲完成时调用)
  fetch_leaderboard() — 拉取排行榜 (用户打开排行榜面板时调用)
"""

import os
import sys
import json
import time
import hashlib
import hmac
import base64
import struct
import secrets
import platform
from typing import Optional, Dict, List

# ═══════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════

SERVER_HOST = 
SERVER_PORT = 9820
SERVER_URL = f'http://{SERVER_HOST}:{SERVER_PORT}'
_LAST_GOOD_SERVER_URL = None

# 共享密钥 (客户端 & 服务端一致)
_SHARED_SECRET = b'SaoMidiPlayer_Leaderboard_2024_v1'

# 本地缓存
_base_dir = (os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
             else os.path.dirname(os.path.abspath(__file__)))
_CACHE_FILE = os.path.join(_base_dir, '.lb_cache.json')
_CACHE_TTL = 120  # 缓存有效期 (秒)


def _normalize_server_url(url: str) -> str:
    url = (url or '').strip().rstrip('/')
    if not url:
        return ''
    if '://' not in url:
        url = 'http://' + url
    return url


def _candidate_server_urls() -> List[str]:
    """返回客户端会尝试的排行榜服务地址列表."""
    urls: List[str] = []

    env_url = _normalize_server_url(os.environ.get('SAO_LEADERBOARD_URL', ''))
    if env_url:
        urls.append(env_url)

    env_host = (os.environ.get('SAO_LEADERBOARD_HOST') or '').strip()
    env_port = (os.environ.get('SAO_LEADERBOARD_PORT') or str(SERVER_PORT)).strip()
    if env_host:
        urls.extend([
            _normalize_server_url(f'https://{env_host}:{env_port}'),
            _normalize_server_url(f'http://{env_host}:{env_port}'),
            _normalize_server_url(f'https://{env_host}'),
            _normalize_server_url(f'http://{env_host}'),
        ])

    urls.extend([
        _normalize_server_url(SERVER_URL),
        _normalize_server_url(f'https://{SERVER_HOST}:{SERVER_PORT}'),
        _normalize_server_url(f'https://{SERVER_HOST}'),
        _normalize_server_url(f'http://localhost:{SERVER_PORT}'),
        _normalize_server_url(f'http://127.0.0.1:{SERVER_PORT}'),
    ])

    out: List[str] = []
    seen = set()
    global _LAST_GOOD_SERVER_URL
    if _LAST_GOOD_SERVER_URL:
        seen.add(_LAST_GOOD_SERVER_URL)
        out.append(_LAST_GOOD_SERVER_URL)
    for url in urls:
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _post_json(path: str, payload: dict, timeout: float) -> Optional[dict]:
    """POST 到第一个可用服务端，成功则返回 JSON 响应."""
    import urllib.request
    import urllib.error
    import ssl

    body = json.dumps(payload).encode('utf-8')
    last_error = None

    for base_url in _candidate_server_urls():
        try:
            req = urllib.request.Request(
                f'{base_url}{path}',
                data=body,
                headers={'Content-Type': 'application/json'},
                method='POST',
            )
            kwargs = {'timeout': timeout}
            if base_url.startswith('https://'):
                kwargs['context'] = ssl._create_unverified_context()
            with urllib.request.urlopen(req, **kwargs) as resp:
                global _LAST_GOOD_SERVER_URL
                _LAST_GOOD_SERVER_URL = base_url
                raw = resp.read().decode('utf-8')
                return json.loads(raw) if raw else {}
        except Exception as e:
            last_error = e
            continue

    if last_error:
        raise last_error
    return None


# ═══════════════════════════════════════════════
#  加密工具 (纯标准库, 无需 pycryptodome)
# ═══════════════════════════════════════════════

def _derive_key(salt: bytes) -> bytes:
    """PBKDF2-SHA256 派生 32 字节密钥."""
    return hashlib.pbkdf2_hmac('sha256', _SHARED_SECRET, salt, 100_000, dklen=32)


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    """XOR stream cipher (key repeated to data length)."""
    klen = len(key)
    return bytes(b ^ key[i % klen] for i, b in enumerate(data))


def _aes_cbc_encrypt(plaintext: bytes, key: bytes) -> tuple:
    """
    AES-256-CBC 加密 (优先使用 cryptography 库, 降级到 XOR stream).
    Returns: (iv_bytes, ciphertext_bytes)
    """
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
    # Fallback: XOR stream cipher with key-derived stream
    stream_key = hashlib.sha256(key + iv).digest() * ((len(plaintext) // 32) + 2)
    ct = _xor_bytes(plaintext, stream_key[:len(plaintext)])
    return iv, ct


def _aes_cbc_decrypt(iv: bytes, ciphertext: bytes, key: bytes) -> bytes:
    """AES-256-CBC 解密, 降级到 XOR stream."""
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


def encrypt_payload(data: dict) -> str:
    """加密 + 签名 → base64 字符串 (用于 HTTP body)."""
    plaintext = json.dumps(data, ensure_ascii=False).encode('utf-8')
    salt = secrets.token_bytes(16)
    key = _derive_key(salt)
    iv, ct = _aes_cbc_encrypt(plaintext, key)
    # HMAC-SHA256 签名
    sig = hmac.new(key, iv + ct, hashlib.sha256).digest()
    # 格式: salt(16) + iv(16) + sig(32) + ciphertext
    packet = salt + iv + sig + ct
    return base64.b64encode(packet).decode('ascii')


def decrypt_payload(b64_data: str) -> dict:
    """解密 + 验签 → dict."""
    raw = base64.b64decode(b64_data)
    salt = raw[:16]
    iv = raw[16:32]
    sig = raw[32:64]
    ct = raw[64:]
    key = _derive_key(salt)
    # 验证签名
    expected_sig = hmac.new(key, iv + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(sig, expected_sig):
        raise ValueError('signature mismatch — data tampered')
    plaintext = _aes_cbc_decrypt(iv, ct, key)
    return json.loads(plaintext.decode('utf-8'))


# ═══════════════════════════════════════════════
#  设备指纹 (匿名唯一标识)
# ═══════════════════════════════════════════════

def _get_device_id() -> str:
    """生成或读取设备唯一 ID (存储在 .device_id 文件)."""
    id_file = os.path.join(_base_dir, '.device_id')
    if os.path.exists(id_file):
        try:
            with open(id_file, 'r') as f:
                did = f.read().strip()
                if did:
                    return did
        except Exception:
            pass
    # 生成新 ID
    did = hashlib.sha256(secrets.token_bytes(32)).hexdigest()[:24]
    try:
        with open(id_file, 'w') as f:
            f.write(did)
    except Exception:
        pass
    return did


def _sanitize_device_name(name: str) -> str:
    raw = (name or '').strip()
    safe = ''.join(ch for ch in raw if ch.isalnum() or ch in ' -_#@.[]()（）【】')
    safe = safe.strip(' -_')
    return (safe or 'Local Device')[:32]


def _get_device_name() -> str:
    """兼容旧逻辑，现返回本地玩家输入的 playerID(username)."""
    try:
        from character_profile import load_profile
        profile = load_profile() or {}
        player_id = _sanitize_device_name(profile.get('username', ''))
        if player_id and player_id != 'Local Device':
            return player_id
    except Exception:
        pass

    env_name = os.environ.get('SAO_PLAYER_ID', '') or os.environ.get('SAO_DEVICE_NAME', '')
    if env_name:
        return _sanitize_device_name(env_name)
    return 'Player'


def get_local_identity() -> Dict[str, str]:
    """返回本机排行榜身份信息。"""
    return {
        'device_id': _get_device_id(),
        'device_name': _get_device_name(),
        'player_id': _get_device_name(),
    }


def _normalize_entries(entries: Optional[List[Dict]]) -> List[Dict]:
    out: List[Dict] = []
    for i, row in enumerate(entries or []):
        item = dict(row or {})
        item.setdefault('rank', i + 1)
        player_id = _sanitize_device_name(
            item.get('player_id', '') or item.get('username', '') or item.get('device_name', '') or 'Player'
        )
        item['player_id'] = player_id
        item['device_name'] = player_id
        item.setdefault('device_id', '')
        out.append(item)
    return out


# ═══════════════════════════════════════════════
#  API 接口
# ═══════════════════════════════════════════════

def upload_stats(username: str = '', level: int = 1, xp: int = 0,
                 songs_played: int = 0, play_time: float = 0,
                 profession: str = '') -> bool:
    """
    上传玩家统计数据到排行榜服务器.
    仅在歌曲播放完成时调用, 最小化流量.

    Returns: True if successful
    """
    try:
        identity = get_local_identity()
        payload = {
            'action': 'upload',
            'device_id': identity['device_id'],
            'device_name': identity['player_id'],
            'player_id': identity['player_id'],
            'username': username or 'Player',
            'level': level,
            'xp': xp,
            'songs_played': songs_played,
            'play_time': round(play_time, 1),
            'profession': profession,
            'timestamp': int(time.time()),
        }
        encrypted = encrypt_payload(payload)
        resp = _post_json('/api/upload', {'data': encrypted}, timeout=5)
        return isinstance(resp, dict) and not resp.get('error')
    except Exception:
        return False


def fetch_leaderboard(sort_by: str = 'xp', limit: int = 50) -> Optional[List[Dict]]:
    """
    从服务器拉取排行榜数据.
    仅在用户打开排行榜面板时调用.

    Args:
        sort_by: 'xp' | 'level' | 'songs_played' | 'play_time'
        limit: 最大返回条数

    Returns:
        排行榜列表 [{rank, username, level, xp, songs_played, play_time, profession}, ...]
        失败返回 None (回退到缓存)
    """
    # 检查缓存
    cache = _load_cache()
    if cache and time.time() - cache.get('ts', 0) < _CACHE_TTL:
        cached_list = cache.get(sort_by)
        if cached_list:
            return _normalize_entries(cached_list)

    try:
        payload = {
            'action': 'fetch',
            'sort_by': sort_by,
            'limit': limit,
            'device_id': _get_device_id(),
            'device_name': _get_device_name(),
            'player_id': _get_device_name(),
        }
        encrypted = encrypt_payload(payload)
        resp_data = _post_json('/api/leaderboard', {'data': encrypted}, timeout=8)

        if 'data' in resp_data:
            result = decrypt_payload(resp_data['data'])
            entries = _normalize_entries(result.get('leaderboard', []))
            # 更新缓存
            _save_cache(sort_by, entries)
            return entries
    except Exception:
        pass

    # 回退到缓存 (即使过期)
    if cache:
        return _normalize_entries(cache.get(sort_by, []))
    return None


def _load_cache() -> Optional[Dict]:
    try:
        if os.path.exists(_CACHE_FILE):
            with open(_CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return None


def _save_cache(sort_by: str, entries: list):
    try:
        cache = _load_cache() or {}
        cache[sort_by] = entries
        cache['ts'] = time.time()
        with open(_CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False)
    except Exception:
        pass
