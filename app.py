from flask import Flask, request, jsonify
import requests
import time
import base64
import json
import urllib3
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import data_pb2
except ImportError:
    import sys
    sys.exit(1)

app = Flask(__name__)
app.json.sort_keys = False

SECRET_KEY = b'Yg&tc%DEuh6%Zc^8'
SECRET_IV = b'6oyZDr22E3ychjM%'

TARGET_URL = "https://loginbp.ppmainecoonghj.com/MajorModifyNickname"
JWT_API_URL = "https://shappno-deploy-hub.lovable.app/token"

GAME_VERSION = "OB55"
UNITY_VERSION = "2018.4.11f1"
USER_AGENT = "Dalvik/2.1.0 (Linux; U; Android 11; SM-A305F Build/RP1A.200720.012)"
DEVELOPERS = "@SHAPPNO_04X"


def generate_error_payload(reason, http_status, extra_data=None):
    payload = {
        "metadata": {
            "author": DEVELOPERS,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        },
        "response_status": "ERROR",
        "error_message": reason
    }
    if extra_data:
        payload["diagnostic_details"] = extra_data
    return jsonify(payload), http_status


def encrypt_message(plaintext):
    cipher = AES.new(SECRET_KEY, AES.MODE_CBC, SECRET_IV)
    return cipher.encrypt(pad(plaintext, AES.block_size))


def decode_ff_name(b64_str):
    try:
        key = b"1e5898ccb8dfdd921f9bdea848768b64a201"
        b64_str = b64_str.strip()
        b64_str += "=" * ((4 - len(b64_str) % 4) % 4)
        encrypted_bytes = base64.b64decode(b64_str)
        decrypted_bytes = bytearray()
        for i, byte in enumerate(encrypted_bytes):
            key_byte = key[i % len(key)]
            decrypted_bytes.append(byte ^ key_byte)
        return decrypted_bytes.decode('utf-8', errors='ignore')
    except Exception as e:
        return f"Error decoding: {str(e)}"


def extract_jwt_info(jwt_token):
    try:
        payload_b64 = jwt_token.split('.')[1]
        payload_b64 += "=" * ((4 - len(payload_b64) % 4) % 4)
        decoded_token = json.loads(base64.urlsafe_b64decode(payload_b64).decode('utf-8'))
        account_id = decoded_token.get("account_id")
        enc_nickname = decoded_token.get("nickname")
        old_name = decode_ff_name(enc_nickname) if enc_nickname else "Unknown"
        region = decoded_token.get("lock_region", "Unknown")
        release_version = decoded_token.get("release_version", "Unknown")
        return account_id, old_name, region, release_version
    except Exception:
        return None, "Unknown", "Unknown", "Unknown"


def fetch_jwt_from_api(uid, password):
    try:
        params = {"uid": uid, "password": password}
        res = requests.get(JWT_API_URL, params=params, verify=False, timeout=20)
        data = res.json()
        if data.get("status") != "success" or not data.get("token"):
            return None, data
        return data["token"], data
    except Exception as e:
        return None, {"error": str(e)}


def execute_nickname_change(jwt_token, target_name, auth_type, token_status, api_meta=None):
    account_id, old_name, region, release_version = extract_jwt_info(jwt_token)

    msg = data_pb2.Message()
    msg.data = target_name.encode("utf-8")
    msg.timestamp = int(time.time() * 1000)

    encrypted_data = encrypt_message(msg.SerializeToString())

    request_headers = {
        "Expect": "100-continue",
        "Authorization": f"Bearer {jwt_token}",
        "X-Unity-Version": UNITY_VERSION,
        "X-GA": "v1 1",
        "ReleaseVersion": GAME_VERSION,
        "Content-Type": "application/octet-stream",
        "User-Agent": USER_AGENT,
        "Connection": "Keep-Alive",
        "Accept-Encoding": "gzip"
    }

    try:
        remote_response = requests.post(
            TARGET_URL,
            data=encrypted_data,
            headers=request_headers,
            verify=False,
            timeout=15
        )

        success_flag = remote_response.status_code == 200

        try:
            raw_text = remote_response.content.decode('utf-8', errors='ignore')
            plaintext = ''.join(char for char in raw_text if ord(char) >= 32)
        except Exception:
            plaintext = remote_response.text

        result = {
            "metadata": {
                "author": DEVELOPERS,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
            },
            "response_status": "SUCCESS" if success_flag else "FAILED",
            "operation_message": "Nickname successfully changed!" if success_flag else "Failed to alter nickname. Verify server status.",
            "http_status_code": remote_response.status_code,
            "account_details": {
                "authentication_method": auth_type,
                "account_id": account_id,
                "old_name": old_name,
                "new_name": target_name,
                "region": region,
                "release_version": release_version,
                "token_lifecycle_state": token_status
            },
            "server_feedback": {
                "headers": dict(remote_response.headers),
                "raw_hexadecimal": remote_response.content.hex(),
                "plaintext_response": plaintext
            }
        }

        if api_meta:
            result["jwt_api_details"] = {
                "access_token": api_meta.get("access_token"),
                "open_id": api_meta.get("open_id"),
                "real_uid": api_meta.get("real_uid"),
                "generation_time": api_meta.get("time")
            }

        return jsonify(result), remote_response.status_code

    except Exception as network_error:
        return generate_error_payload(
            "Internal Server Error while communicating with game servers.",
            500,
            str(network_error)
        )


@app.route("/", methods=["GET"])
def api_documentation():
    return jsonify({
        "system_information": {
            "application": "Free Fire Nickname Modifier API",
            "developer": DEVELOPERS,
            "game_version_target": GAME_VERSION,
            "jwt_source": JWT_API_URL,
            "description": "JSON API for modifying game nicknames using SHAPPNO JWT Generator."
        },
        "usage_guide": {
            "By using UID and Password": "/guest?uid={uid}&password={password}&name={new_name}",
            "By using Direct JWT Token": "/token?jwt={jwt_token}&name={new_name}"
        }
    })


@app.route("/guest", methods=["GET"])
def process_guest_login():
    game_uid = request.args.get("uid")
    game_pwd = request.args.get("password")
    desired_name = request.args.get("name")

    if not all([game_uid, game_pwd, desired_name]):
        return generate_error_payload("Missing required parameters: uid, password, name", 400)

    jwt_token, api_meta = fetch_jwt_from_api(game_uid, game_pwd)

    if not jwt_token:
        return generate_error_payload(
            "Failed to generate JWT from SHAPPNO API.",
            401,
            api_meta
        )

    return execute_nickname_change(
        jwt_token=jwt_token,
        target_name=desired_name,
        auth_type="UID_PASSWORD_VIA_JWT_API",
        token_status="generated_by_shappno_api",
        api_meta=api_meta
    )


@app.route("/token", methods=["GET"])
def process_token_login():
    direct_jwt = request.args.get("jwt")
    desired_name = request.args.get("name")

    if not desired_name or not direct_jwt:
        return generate_error_payload(
            "Missing required parameters: jwt and name", 400
        )

    return execute_nickname_change(
        jwt_token=direct_jwt,
        target_name=desired_name,
        auth_type="TOKEN_BASED_AUTH",
        token_status="direct_jwt_input"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)