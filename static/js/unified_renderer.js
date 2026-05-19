/**
 * 统一渲染器 - 同时管理 VRM 和 Live2D 引擎
 * 支持引擎预加载、模型缓存、快速切换
 */

// ========== 模型缓存 ==========
class ModelCache {
    constructor(maxSize = 5) {
        this.cache = new Map();
        this.maxSize = maxSize;
        this.accessOrder = [];
    }

    get(key) {
        if (this.cache.has(key)) {
            this._updateAccessOrder(key);
            return this.cache.get(key);
        }
        return null;
    }

    set(key, value) {
        if (this.cache.size >= this.maxSize) {
            this._evictLRU();
        }
        this.cache.set(key, value);
        this._updateAccessOrder(key);
    }

    has(key) {
        return this.cache.has(key);
    }

    delete(key) {
        const index = this.accessOrder.indexOf(key);
        if (index > -1) {
            this.accessOrder.splice(index, 1);
        }
        this.cache.delete(key);
    }

    clear() {
        for (const [key, model] of this.cache) {
            if (model && model.dispose) {
                model.dispose();
            }
        }
        this.cache.clear();
        this.accessOrder = [];
    }

    _updateAccessOrder(key) {
        const index = this.accessOrder.indexOf(key);
        if (index > -1) {
            this.accessOrder.splice(index, 1);
        }
        this.accessOrder.push(key);
    }

    _evictLRU() {
        const lruKey = this.accessOrder.shift();
        const lruModel = this.cache.get(lruKey);

        if (lruModel) {
            if (lruModel.scene) {
                // VRM 模型
                lruModel.scene.traverse(obj => {
                    if (obj.geometry) obj.geometry.dispose();
                    if (obj.material) {
                        if (Array.isArray(obj.material)) {
                            obj.material.forEach(m => m.dispose());
                        } else {
                            obj.material.dispose();
                        }
                    }
                    if (obj.texture) obj.texture.dispose();
                });
            } else if (lruModel.destroy) {
                // Live2D 模型
                lruModel.destroy();
            }
        }

        this.cache.delete(lruKey);
        console.log('[Cache] Evicted:', lruKey);
    }

    getStats() {
        return {
            size: this.cache.size,
            maxSize: this.maxSize,
            keys: Array.from(this.cache.keys())
        };
    }
}

// ========== 性能监控 ==========
class PerformanceMonitor {
    constructor() {
        this.metrics = {
            engineInitTime: {},
            modelLoadTime: {},
            cacheHits: 0,
            cacheMisses: 0
        };
    }

    recordEngineInit(engineType, duration) {
        this.metrics.engineInitTime[engineType] = duration;
    }

    recordModelLoad(modelPath, duration, fromCache) {
        this.metrics.modelLoadTime[modelPath] = {
            duration,
            fromCache,
            timestamp: Date.now()
        };

        if (fromCache) {
            this.metrics.cacheHits++;
        } else {
            this.metrics.cacheMisses++;
        }
    }

    getReport() {
        const total = this.metrics.cacheHits + this.metrics.cacheMisses;
        return {
            ...this.metrics,
            cacheHitRate: total > 0
                ? (this.metrics.cacheHits / total * 100).toFixed(2) + '%'
                : '0%',
            totalModels: Object.keys(this.metrics.modelLoadTime).length
        };
    }
}

// ========== 统一渲染器 ==========
class UnifiedRenderer {
    constructor() {
        this.engines = {};
        this.currentRenderer = null;
        this.currentEngineType = null;
        this.modelCache = new ModelCache(5);
        this.perfMonitor = new PerformanceMonitor();
        this.animationFrameId = null;
        this.isInitialized = false;
    }

    /**
     * 初始化引擎
     * @param {string} engineType - 'vrm' 或 'live2d'
     * @returns {Promise<{success: boolean}>}
     */
    async initEngine(engineType) {
        const startTime = performance.now();

        try {
            switch (engineType) {
                case 'vrm':
                    await this._initVRMEngine();
                    break;
                case 'live2d':
                    await this._initLive2DEngine();
                    break;
                default:
                    throw new Error(`Unknown engine type: ${engineType}`);
            }

            const duration = performance.now() - startTime;
            this.perfMonitor.recordEngineInit(engineType, duration);
            console.log(`[Renderer] ${engineType} engine initialized in ${duration.toFixed(2)}ms`);

            return { success: true };
        } catch (error) {
            console.error(`[Renderer] Failed to init ${engineType}:`, error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 初始化 VRM 引擎 (Three.js)
     */
    async _initVRMEngine() {
        if (this.engines.vrm) {
            console.log('[Renderer] VRM engine already initialized');
            return;
        }

        const container = document.getElementById('render-container');
        if (!container) {
            throw new Error('render-container not found');
        }

        // 创建 canvas
        const canvas = document.createElement('canvas');
        canvas.id = 'vrm-canvas';
        canvas.style.display = 'none';
        container.appendChild(canvas);

        // 初始化 Three.js
        const scene = new THREE.Scene();
        const camera = new THREE.PerspectiveCamera(
            30,
            container.clientWidth / container.clientHeight,
            0.1,
            1000
        );
        camera.position.set(0, 1.3, 2.5);

        const renderer = new THREE.WebGLRenderer({
            canvas: canvas,
            alpha: true,
            antialias: true
        });
        renderer.setSize(container.clientWidth, container.clientHeight);
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
        renderer.setClearColor(0x000000, 0);  // 透明背景

        // 灯光
        const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
        scene.add(ambientLight);

        const directionalLight = new THREE.DirectionalLight(0xffffff, 0.6);
        directionalLight.position.set(1, 1, 1).normalize();
        scene.add(directionalLight);

        // 控制器
        let controls = null;
        if (THREE.OrbitControls) {
            controls = new THREE.OrbitControls(camera, canvas);
            controls.target.set(0, 1.3, 0);
            controls.update();
        }

        // GLTFLoader
        const loader = new THREE.GLTFLoader();

        // 注册 VRM 插件
        if (typeof THREE_VRM !== 'undefined' && THREE_VRM.VRMLoaderPlugin) {
            loader.register(parser => new THREE_VRM.VRMLoaderPlugin(parser));
        }

        this.engines.vrm = {
            scene,
            camera,
            renderer,
            controls,
            loader,
            canvas,
            currentModel: null,
            ready: true
        };

        console.log('[Renderer] VRM engine initialized');
    }

    /**
     * 初始化 Live2D 引擎 (PixiJS)
     */
    async _initLive2DEngine() {
        if (this.engines.live2d) {
            console.log('[Renderer] Live2D engine already initialized');
            return;
        }

        const container = document.getElementById('render-container');
        if (!container) {
            throw new Error('render-container not found');
        }

        // 初始化 PixiJS
        const app = new PIXI.Application({
            view: document.createElement('canvas'),
            width: container.clientWidth,
            height: container.clientHeight,
            transparent: true,
            autoStart: false,
            resizeTo: container
        });

        app.view.style.display = 'none';
        container.appendChild(app.view);

        this.engines.live2d = {
            app,
            canvas: app.view,
            currentModel: null,
            ready: true
        };

        console.log('[Renderer] Live2D engine initialized');
    }

    /**
     * 加载模型
     * @param {string} engineType - 'vrm' 或 'live2d'
     * @param {string} modelPath - 模型路径
     * @returns {Promise<{success: boolean, fromCache: boolean}>}
     */
    async loadModel(engineType, modelPath) {
        const cacheKey = `${engineType}:${modelPath}`;
        const startTime = performance.now();
        const fromCache = this.modelCache.has(cacheKey);

        try {
            // 隐藏当前渲染器
            this._hideAllRenderers();

            // 停止当前渲染循环
            if (this.animationFrameId) {
                cancelAnimationFrame(this.animationFrameId);
                this.animationFrameId = null;
            }

            let result;
            switch (engineType) {
                case 'vrm':
                    result = await this._loadVRMModel(modelPath, cacheKey);
                    break;
                case 'live2d':
                    result = await this._loadLive2DModel(modelPath, cacheKey);
                    break;
                default:
                    throw new Error(`Unknown engine type: ${engineType}`);
            }

            const duration = performance.now() - startTime;
            this.perfMonitor.recordModelLoad(modelPath, duration, fromCache);
            console.log(`[Renderer] Model loaded in ${duration.toFixed(2)}ms (cache: ${fromCache})`);

            this.currentEngineType = engineType;
            return { success: true, fromCache, duration };
        } catch (error) {
            console.error(`[Renderer] Failed to load model:`, error);
            return { success: false, error: error.message };
        }
    }

    /**
     * 加载 VRM 模型
     */
    async _loadVRMModel(modelPath, cacheKey) {
        const engine = this.engines.vrm;
        if (!engine || !engine.ready) {
            throw new Error('VRM engine not ready');
        }

        // 检查缓存
        let vrm = this.modelCache.get(cacheKey);
        if (vrm) {
            console.log('[Renderer] Using cached VRM model');
        } else {
            // 加载新模型 - 使用 XMLHttpRequest 代替 fetch（兼容 file:/// 协议）
            console.log('[Renderer] Loading VRM model:', modelPath);

            const gltf = await new Promise((resolve, reject) => {
                // 使用 XMLHttpRequest 加载文件（兼容 file:/// 协议）
                const xhr = new XMLHttpRequest();
                xhr.open('GET', modelPath, true);
                xhr.responseType = 'arraybuffer';

                xhr.onprogress = (event) => {
                    if (event.total > 0) {
                        const percent = Math.round((event.loaded / event.total) * 100);
                        this._updateStatus(`Loading VRM: ${percent}%`);
                    }
                };

                xhr.onload = function() {
                    if (xhr.status === 200 || xhr.status === 0) { // status 0 for file:///
                        // 使用 GLTFLoader.parse 代替 load
                        engine.loader.parse(xhr.response, '', function(gltf) {
                            resolve(gltf);
                        }, function(error) {
                            reject(error);
                        });
                    } else {
                        reject(new Error(`HTTP ${xhr.status}: ${xhr.statusText}`));
                    }
                };

                xhr.onerror = function() {
                    reject(new Error('Network error'));
                };

                xhr.send();
            });

            // 解析 VRM
            if (gltf.userData && gltf.userData.vrm) {
                vrm = gltf.userData.vrm;
            } else if (typeof THREE_VRM !== 'undefined' && THREE_VRM.VRM) {
                vrm = await THREE_VRM.VRM.from(gltf);
            } else {
                // 降级为普通 GLTF
                vrm = { scene: gltf.scene, update: () => {} };
            }

            // 存入缓存
            this.modelCache.set(cacheKey, vrm);
        }

        // 移除旧模型（不销毁）
        if (engine.currentModel && engine.currentModel !== vrm) {
            engine.scene.remove(engine.currentModel.scene);
        }

        // 添加新模型
        engine.scene.add(vrm.scene);
        engine.currentModel = vrm;

        // 自动调整相机
        if (vrm.scene) {
            const box = new THREE.Box3().setFromObject(vrm.scene);
            const center = box.getCenter(new THREE.Vector3());
            const size = box.getSize(new THREE.Vector3());
            const maxDim = Math.max(size.x, size.y, size.z);
            const dist = maxDim * 2;

            engine.camera.position.set(
                center.x,
                center.y + size.y * 0.3,
                center.z + dist
            );
            engine.camera.lookAt(center);

            if (engine.controls) {
                engine.controls.target.copy(center);
                engine.controls.update();
            }
        }

        // 显示 VRM 渲染器
        engine.canvas.style.display = 'block';
        this.currentRenderer = engine.canvas;

        // 启动渲染循环
        this._startVRMRenderLoop();

        this._updateStatus('VRM Loaded');
        return vrm;
    }

    /**
     * 加载 Live2D 模型
     */
    async _loadLive2DModel(modelPath, cacheKey) {
        const engine = this.engines.live2d;
        if (!engine || !engine.ready) {
            throw new Error('Live2D engine not ready');
        }

        // 检查缓存
        let model = this.modelCache.get(cacheKey);
        if (model) {
            console.log('[Renderer] Using cached Live2D model');
        } else {
            // 加载新模型
            this._updateStatus('Loading Live2D...');
            model = await PIXI.live2d.Live2DModel.from(modelPath);

            // 存入缓存
            this.modelCache.set(cacheKey, model);
        }

        // 移除旧模型
        if (engine.currentModel && engine.currentModel !== model) {
            engine.app.stage.removeChild(engine.currentModel);
        }

        // 添加新模型
        engine.app.stage.addChild(model);
        engine.currentModel = model;

        // 设置模型位置和缩放
        model.anchor.set(0.5, 0.5);
        model.x = engine.app.view.width / 2;
        model.y = engine.app.view.height / 2;

        // 显示 Live2D 渲染器
        engine.canvas.style.display = 'block';
        this.currentRenderer = engine.canvas;

        // 启动 Live2D 渲染
        engine.app.start();

        this._updateStatus('Live2D Loaded');
        return model;
    }

    /**
     * 启动 VRM 渲染循环
     */
    _startVRMRenderLoop() {
        const engine = this.engines.vrm;
        if (!engine) return;

        const animate = () => {
            this.animationFrameId = requestAnimationFrame(animate);

            // 更新控制器
            if (engine.controls) {
                engine.controls.update();
            }

            // 更新 VRM 模型
            if (engine.currentModel && engine.currentModel.update) {
                engine.currentModel.update(0.016); // ~60fps
            }

            // 渲染场景
            engine.renderer.render(engine.scene, engine.camera);
        };

        animate();
    }

    /**
     * 隐藏所有渲染器
     */
    _hideAllRenderers() {
        if (this.engines.vrm) {
            this.engines.vrm.canvas.style.display = 'none';
        }
        if (this.engines.live2d) {
            this.engines.live2d.canvas.style.display = 'none';
            this.engines.live2d.app.stop();
        }
    }

    /**
     * 更新状态显示
     */
    _updateStatus(text) {
        const statusBar = document.getElementById('status-bar');
        if (statusBar) {
            statusBar.textContent = text;
        }
    }

    /**
     * 获取缓存统计
     */
    getCacheStats() {
        return this.modelCache.getStats();
    }

    /**
     * 获取性能报告
     */
    getPerformanceReport() {
        return this.perfMonitor.getReport();
    }

    /**
     * 清空缓存
     */
    clearCache() {
        this.modelCache.clear();
        console.log('[Renderer] Cache cleared');
    }

    /**
     * 清理所有资源
     */
    cleanup() {
        // 停止渲染循环
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
            this.animationFrameId = null;
        }

        // 清理 VRM 引擎
        if (this.engines.vrm) {
            const engine = this.engines.vrm;
            if (engine.currentModel && engine.currentModel.scene) {
                engine.scene.remove(engine.currentModel.scene);
            }
            if (engine.renderer) {
                engine.renderer.dispose();
            }
            if (engine.canvas && engine.canvas.parentNode) {
                engine.canvas.parentNode.removeChild(engine.canvas);
            }
            this.engines.vrm = null;
        }

        // 清理 Live2D 引擎
        if (this.engines.live2d) {
            const engine = this.engines.live2d;
            if (engine.currentModel) {
                engine.currentModel.destroy();
            }
            if (engine.app) {
                engine.app.destroy(true);
            }
            this.engines.live2d = null;
        }

        // 清空缓存
        this.modelCache.clear();

        this.currentRenderer = null;
        this.currentEngineType = null;
        this.isInitialized = false;

        console.log('[Renderer] Cleanup complete');
    }
}

// ========== 全局实例 ==========
window.renderer = new UnifiedRenderer();

// ========== Python 调用接口 ==========
window.initEngine = async (engineType) => {
    return await window.renderer.initEngine(engineType);
};

window.loadModel = async (engineType, modelPath) => {
    return await window.renderer.loadModel(engineType, modelPath);
};

window.getCacheStats = () => {
    return window.renderer.getCacheStats();
};

window.getPerformanceReport = () => {
    return window.renderer.getPerformanceReport();
};

window.clearCache = () => {
    window.renderer.clearCache();
};

window.cleanup = () => {
    window.renderer.cleanup();
};

// 窗口大小调整
window.addEventListener('resize', () => {
    const container = document.getElementById('render-container');
    if (!container) return;

    const width = container.clientWidth;
    const height = container.clientHeight;

    // 更新 VRM 引擎
    if (window.renderer.engines.vrm) {
        const engine = window.renderer.engines.vrm;
        engine.camera.aspect = width / height;
        engine.camera.updateProjectionMatrix();
        engine.renderer.setSize(width, height);
    }

    // 更新 Live2D 引擎
    if (window.renderer.engines.live2d) {
        const engine = window.renderer.engines.live2d;
        engine.app.renderer.resize(width, height);
    }
});

console.log('[Renderer] Unified renderer loaded');
