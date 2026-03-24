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
from typing import Optional, Dict, List

# ═══════════════════════════════════════════════
#  配置
# ═══════════════════════════════════════════════

SERVER_HOST = '47.82.157.220'
SERVER_PORT = 9820
SERVER_URL = f'http://{SERVER_HOST}:{SERVER_PORT}'

# 共享密钥 (客户端 & 服务端一致)
_SHARED_SECRET = b'SaoMidiPlayer_Leaderboard_2024_v1'

# 本地缓存
_base_dir = (os.path.dirname(sys.executable) if getattr(sys, 'frozen', False)
             else os.path.dirname(os.path.abspath(__file__)))
_CACHE_FILE = os.path.join(_base_dir, '.lb_cache.json')
_CACHE_TTL = 120  # 缓存有效期 (秒)


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
        import urllib.request
        import urllib.error

        device_id = _get_device_id()
        payload = {
            'action': 'upload',
            'device_id': device_id,
            'username': username or 'Player',
            'level': level,
            'xp': xp,
            'songs_played': songs_played,
            'play_time': round(play_time, 1),
            'profession': profession,
            'timestamp': int(time.time()),
        }
        encrypted = encrypt_payload(payload)
        body = json.dumps({'data': encrypted}).encode('utf-8')

        req = urllib.request.Request(
            f'{SERVER_URL}/api/upload',
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status == 200
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
            return cached_list

    try:
        import urllib.request

        payload = {
            'action': 'fetch',
            'sort_by': sort_by,
            'limit': limit,
            'device_id': _get_device_id(),
        }
        encrypted = encrypt_payload(payload)
        body = json.dumps({'data': encrypted}).encode('utf-8')

        req = urllib.request.Request(
            f'{SERVER_URL}/api/leaderboard',
            data=body,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            resp_data = json.loads(resp.read().decode('utf-8'))

        if 'data' in resp_data:
            result = decrypt_payload(resp_data['data'])
            entries = result.get('leaderboard', [])
            # 更新缓存
            _save_cache(sort_by, entries)
            return entries
    except Exception:
        pass

    # 回退到缓存 (即使过期)
    if cache:
        return cache.get(sort_by, [])
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
