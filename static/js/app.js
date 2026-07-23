/**
 * GitHub deb 更新工具 - 前端 JavaScript
 */

const utils = {
    confirm(message) {
        return window.confirm(message);
    },

    formatSize(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },

    formatDate(date) {
        return new Date(date).toLocaleString('zh-CN');
    },

    /** 从 FastAPI / 普通 JSON 响应中提取错误信息 */
    extractError(payload, fallback = '操作失败') {
        if (!payload) return fallback;
        if (typeof payload === 'string') return payload;
        if (payload.message) return payload.message;
        if (typeof payload.detail === 'string') return payload.detail;
        if (Array.isArray(payload.detail)) {
            return payload.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
        }
        return fallback;
    },
};

const api = {
    async request(url, options = {}) {
        const response = await fetch(url, options);
        let data = null;
        const contentType = response.headers.get('content-type') || '';
        if (contentType.includes('application/json')) {
            data = await response.json().catch(() => null);
        } else {
            const text = await response.text().catch(() => '');
            data = text ? { message: text } : null;
        }

        if (!response.ok) {
            const err = new Error(utils.extractError(data, `HTTP ${response.status}`));
            err.status = response.status;
            err.data = data;
            throw err;
        }
        return data;
    },

    get(url) {
        return this.request(url);
    },

    post(url, data = null, asJson = true) {
        if (data instanceof FormData) {
            return this.request(url, { method: 'POST', body: data });
        }
        if (data instanceof URLSearchParams || asJson === false) {
            return this.request(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: data instanceof URLSearchParams ? data.toString() : (data || ''),
            });
        }
        // 空 POST（如 upgrade-all）不带 body，避免某些客户端解析问题
        if (data == null) {
            return this.request(url, { method: 'POST' });
        }
        return this.request(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
    },

    delete(url) {
        return this.request(url, { method: 'DELETE' });
    },
};

/**
 * WebSocket 升级进度
 * 支持超时、错误兜底，避免“点了没反应”
 */
class UpgradeWebSocket {
    constructor(packageName, callbacks = {}) {
        this.packageName = packageName;
        this.callbacks = callbacks;
        this.ws = null;
        this._closed = false;
        this._terminal = false; // completed / error 只触发一次
        this._gotMessage = false;
        this._timeoutId = null;
        this.timeoutMs = callbacks.timeoutMs || 10 * 60 * 1000; // 10 分钟
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}/updates/ws/upgrade/${encodeURIComponent(this.packageName)}`;

        try {
            this.ws = new WebSocket(url);
        } catch (e) {
            this._fail('无法建立 WebSocket 连接');
            return;
        }

        this._timeoutId = setTimeout(() => {
            this._fail('操作超时，请检查网络或服务日志');
            this.close();
        }, this.timeoutMs);

        this.ws.onopen = () => {
            if (this.callbacks.onOpen) this.callbacks.onOpen();
        };

        this.ws.onmessage = (event) => {
            let data;
            try {
                data = JSON.parse(event.data);
            } catch (e) {
                return;
            }

            this._gotMessage = true;
            if (this.callbacks.onMessage) this.callbacks.onMessage(data);

            switch (data.status) {
                case 'checking':
                    if (this.callbacks.onChecking) this.callbacks.onChecking(data);
                    break;
                case 'downloading':
                    if (this.callbacks.onDownloading) this.callbacks.onDownloading(data);
                    break;
                case 'installing':
                    if (this.callbacks.onInstalling) this.callbacks.onInstalling(data);
                    break;
                case 'completed':
                    this._complete(data);
                    break;
                case 'error':
                    this._fail(data.message || '更新失败', data);
                    break;
            }
        };

        this.ws.onerror = () => {
            // 真正的失败留给 onclose 判断，避免和 message 重复
        };

        this.ws.onclose = () => {
            this._clearTimeout();
            // 连接意外断开且未收到终态
            if (!this._terminal) {
                this._fail(this._gotMessage ? '连接已断开' : 'WebSocket 连接失败');
            }
            if (this.callbacks.onClose) this.callbacks.onClose();
        };
    }

    _complete(data) {
        if (this._terminal) return;
        this._terminal = true;
        this._clearTimeout();
        if (this.callbacks.onCompleted) this.callbacks.onCompleted(data);
        this.close();
    }

    _fail(message, data = null) {
        if (this._terminal) return;
        this._terminal = true;
        this._clearTimeout();
        if (this.callbacks.onError) {
            this.callbacks.onError(data || { status: 'error', message });
        }
        this.close();
    }

    _clearTimeout() {
        if (this._timeoutId) {
            clearTimeout(this._timeoutId);
            this._timeoutId = null;
        }
    }

    close() {
        this._closed = true;
        this._clearTimeout();
        if (this.ws) {
            try {
                this.ws.close();
            } catch (e) {
                /* ignore */
            }
            this.ws = null;
        }
    }
}

window.utils = utils;
window.api = api;
window.UpgradeWebSocket = UpgradeWebSocket;
