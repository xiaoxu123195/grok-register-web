import logging

from flask import Blueprint, jsonify, redirect, render_template, request, session

logger = logging.getLogger(__name__)

auth_bp = Blueprint('auth', __name__)


def _client_id():
    return request.remote_addr or 'unknown'


def init_auth_api(gate):
    @auth_bp.route('/login', methods=['GET', 'POST'])
    def login():
        # Nothing to log into when the gate is off, and an already-signed-in
        # operator should not stare at a login form.
        if not gate.enabled or gate.is_authenticated(session):
            return redirect('/')

        if request.method == 'GET':
            return render_template('login.html', error='', retry_after=0)

        client = _client_id()
        retry_after = gate.throttle.retry_after(client)
        if retry_after > 0:
            logger.warning('Rejected login attempt from %s during lockout', client)
            return render_template(
                'login.html',
                error=f'尝试过于频繁，请在 {int(retry_after) + 1} 秒后重试',
                retry_after=int(retry_after) + 1,
            ), 429

        if gate.verify(request.form.get('password', '')):
            gate.throttle.reset(client)
            gate.mark_authenticated(session)
            logger.info('Admin console login succeeded from %s', client)
            return redirect('/')

        lockout = gate.throttle.record_failure(client)
        logger.warning('Admin console login failed from %s', client)
        if lockout:
            message = f'口令错误次数过多，已锁定 {int(lockout)} 秒'
        else:
            message = '口令错误'
        return render_template('login.html', error=message, retry_after=int(lockout)), 401

    @auth_bp.route('/api/auth/logout', methods=['POST'])
    def logout():
        gate.sign_out(session)
        return jsonify({'success': True, 'data': None, 'message': '已退出登录'})

    @auth_bp.route('/api/auth/status', methods=['GET'])
    def status():
        return jsonify({
            'success': True,
            'data': {
                'enabled': gate.enabled,
                'authenticated': gate.is_authenticated(session),
            },
            'message': '',
        })

    return auth_bp
