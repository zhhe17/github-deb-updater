/**
 * GitHub deb 更新工具 - 前端 JavaScript
 */

// 通用工具函数
const utils = {
    /**
     * 显示确认对话框
     */
    confirm(message) {
        return window.confirm(message);
    },

    /**
     * 格式化文件大小
     */
    formatSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    },

    /**
     * 格式化日期
     */
    formatDate(date) {
        return new Date(date).toLocaleString('zh-CN');
    },
};

// API 请求封装
const api = {
    /**
     * 发送 GET 请求
     */
    async get(url) {
        const response = await fetch(url);
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    },

    /**
     * 发送 POST 请求
     */
    async post(url, data = {}) {
        const response = await fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data),
        });
        if (!response.ok) {
            const error = await response.json().catch(() => ({}));
            throw new Error(error.detail || `HTTP error! status: ${response.status}`);
        }
        return response.json();
    },

    /**
     * 发送 DELETE 请求
     */
    async delete(url) {
        const response = await fetch(url, {
            method: 'DELETE',
        });
        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
    },
};

// WebSocket 连接管理
class UpgradeWebSocket {
    constructor(packageName, callbacks = {}) {
        this.packageName = packageName;
        this.callbacks = callbacks;
        this.ws = null;
    }

    connect() {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${window.location.host}/updates/ws/upgrade/${this.packageName}`;
        
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            console.log('WebSocket connected');
            if (this.callbacks.onOpen) {
                this.callbacks.onOpen();
            }
        };

        this.ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log('WebSocket message:', data);
            
            if (this.callbacks.onMessage) {
                this.callbacks.onMessage(data);
            }

            // 根据状态调用对应回调
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
                    if (this.callbacks.onCompleted) this.callbacks.onCompleted(data);
                    this.close();
                    break;
                case 'error':
                    if (this.callbacks.onError) this.callbacks.onError(data);
                    this.close();
                    break;
            }
        };

        this.ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            if (this.callbacks.onError) {
                this.callbacks.onError({ status: 'error', message: '连接错误' });
            }
        };

        this.ws.onclose = () => {
            console.log('WebSocket closed');
            if (this.callbacks.onClose) {
                this.callbacks.onClose();
            }
        };
    }

    close() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }
}

// 导出到全局
window.utils = utils;
window.api = api;
window.UpgradeWebSocket = UpgradeWebSocket;
