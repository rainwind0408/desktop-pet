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

        // 检查 SDK 是否可用
        if (typeof PIXI === 'undefined') {
            throw new Error('PIXI not loaded');
        }
        if (!PIXI.live2d || !PIXI.live2d.Live2DModel) {
            // 尝试等待 SDK 初始化
            console.warn('[Renderer] PIXI.live2d.Live2DModel not ready, waiting...');
            await new Promise((resolve, reject) => {
                let attempts = 0;
                const check = setInterval(() => {
                    attempts++;
                    if (PIXI.live2d && PIXI.live2d.Live2DModel) {
                        clearInterval(check);
                        resolve();
                    } else if (attempts > 100) {  // 10 秒超时
                        clearInterval(check);
                        reject(new Error('Live2DModel not available (SDK not loaded correctly)'));
                    }
                }, 100);
            });
        }

        const container = document.getElementById('render-container');
        if (!container) {
            throw new Error('render-container not found');
        }

        // 确保容器有有效尺寸（布局未完成时使用默认值）
        const w = container.clientWidth || 320;
        const h = container.clientHeight || 380;

        // 增加重试机制
        for (let retry = 0; retry < 3; retry++) {
            try {
                // 初始化 PixiJS
                const app = new PIXI.Application({
                    view: document.createElement('canvas'),
                    width: w,
                    height: h,
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
                return;  // 成功退出
            } catch (e) {
                console.warn(`[Renderer] Live2D init attempt ${retry + 1} failed:`, e.message);
                if (retry === 2) throw e;  // 最后一次仍失败则抛出
                await new Promise(r => setTimeout(r, 1000));  // 等 1 秒重试
            }
        }
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

        // 初始化动画控制器
        if (typeof AnimationController !== 'undefined') {
            if (engine.animCtrl) {
                engine.animCtrl.dispose();
            }
            engine.animCtrl = new AnimationController(engine.scene, vrm);
            engine.animCtrl.init();
            console.log('[Renderer] AnimationController initialized for VRM');
        }

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
            if (PIXI.live2d && PIXI.live2d.Live2DModel) {
                console.log('[Renderer] Loading Live2D model via PIXI.live2d.Live2DModel');
                console.log('[Renderer] Model URL:', modelPath);
                try {
                    model = await PIXI.live2d.Live2DModel.from(modelPath);
                    console.log('[Renderer] Live2DModel.from() resolved successfully');
                } catch (loadErr) {
                    console.error('[Renderer] Live2DModel.from() FAILED:', loadErr.message);
                    // 尝试获取更多网络错误细节
                    if (loadErr.response) {
                        console.error('[Renderer] HTTP status:', loadErr.response.status, loadErr.response.statusText);
                    }
                    if (loadErr.stack) {
                        console.error('[Renderer] Stack:', loadErr.stack.split('\n').slice(0, 4).join('\n'));
                    }
                    // 重新抛出让上层 catch 处理
                    throw loadErr;
                }
            } else if (typeof window.Live2DModel !== 'undefined') {
                console.log('[Renderer] Using window.Live2DModel fallback');
                model = await window.Live2DModel.from(modelPath);
            } else {
                console.error('[Renderer] Live2D SDK check:', {
                    PIXI: typeof PIXI,
                    live2d: typeof PIXI !== 'undefined' ? typeof PIXI.live2d : 'N/A',
                    Live2DModel: typeof PIXI !== 'undefined' && PIXI.live2d ? typeof PIXI.live2d.Live2DModel : 'N/A',
                    window_Live2DModel: typeof window.Live2DModel
                });
                throw new Error('Live2DModel not available (SDK not loaded correctly)');
            }

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

            // 更新骨骼动画 Mixer（优先使用 AnimationController）
            if (engine.animCtrl) {
                engine.animCtrl.update(0.016);
            } else if (engine.mixer) {
                engine.mixer.update(0.016);
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
            if (engine.animCtrl) {
                engine.animCtrl.dispose();
                engine.animCtrl = null;
            }
            if (engine.mixer) {
                engine.mixer.stopAllAction();
                engine.mixer = null;
            }
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

// ========== 动画控制接口 ==========

// ========== 角色级映射覆盖（由 Python 端设置） ==========
window._characterOverrides = {
    expressionMap: null,  // 语义名 → 模型实际表情名
    motionMap: null       // 语义名 → { group, index }
};

/**
 * 设置角色专属的表情/动作映射（覆盖默认值）
 * @param {Object|null} expressionMap - { "happy": "Smile", "sad": "Sad", ... }
 * @param {Object|null} motionMap - { "wave": { group: "TapBody", index: 0 }, ... }
 */
window.setCharacterOverrides = (expressionMap, motionMap) => {
    window._characterOverrides.expressionMap = expressionMap || null;
    window._characterOverrides.motionMap = motionMap || null;
    console.log('[Animation] Character overrides set:', {
        expressionMap: expressionMap ? Object.keys(expressionMap).length + ' entries' : 'null',
        motionMap: motionMap ? Object.keys(motionMap).length + ' entries' : 'null'
    });
};

// 获取有效的表情映射（优先角色级，回退默认）
function getEffectiveExpressionMap() {
    return window._characterOverrides.expressionMap || EXPRESSION_ONLY_MAP;
}

// 获取有效的 motion 映射（优先角色级，回退默认）
function getEffectiveLive2DMotionMap() {
    return window._characterOverrides.motionMap || LIVE2D_MOTION_MAP;
}

// ========== 语义名 → 执行方式映射 ==========
const MOTION_MAP = {
    'wave':        { type: 'skeletal', anim: 'wave' },
    'nod_fast':    { type: 'skeletal', anim: 'nod_fast' },
    'shake':       { type: 'skeletal', anim: 'shake' },
    'bow':         { type: 'skeletal', anim: 'bow' },
    'wave_arm':    { type: 'skeletal', anim: 'wave_arm' },
    'greet':       { type: 'skeletal', anim: 'greet' },
    'sit':         { type: 'skeletal', anim: 'sit' },
    'wave_both':   { type: 'skeletal', anim: 'wave_both' },
    'nod_slow':    { type: 'skeletal', anim: 'nod_slow' },
    'head_tilt':   { type: 'skeletal', anim: 'head_tilt' },
    'shrug':       { type: 'skeletal', anim: 'shoulder_shrug' },
    'happy':       { type: 'expression', name: 'happy' },
    'sad':         { type: 'expression', name: 'sad' },
    'angry':       { type: 'expression', name: 'angry' },
    'surprised':   { type: 'expression', name: 'surprised' },
    'sleepy':      { type: 'expression', name: 'relaxed' },
    'scared':      { type: 'expression', name: 'surprised' },
    'sit_quietly': { type: 'skeletal', anim: 'sit' },
    'think':       { type: 'expression', name: 'neutral' }
};

// 兼容旧代码的表情映射
const expressionMap = {
    'happy': 'happy',
    'joy': 'happy',
    'surprised': 'surprised',
    'sad': 'sad',
    'upset': 'angry',
    'angry': 'angry',
    'neutral': 'neutral'
};

// ========== Live2D Motion Group 映射 ==========
const LIVE2D_MOTION_MAP = {
    'wave':        { group: 'TapBody', index: 0 },
    'nod_fast':    { group: 'TapBody', index: 0 },
    'shake':       { group: 'TapBody', index: 1 },
    'bow':         { group: 'TapBody', index: 0 },
    'wave_arm':    { group: 'TapBody', index: 0 },
    'greet':       { group: 'TapBody', index: 0 },
    'happy':       { group: 'TapBody', index: 0 },
    'sad':         { group: 'TapBody', index: 1 },
    'angry':       { group: 'TapBody', index: 2 },
    'surprised':   { group: 'TapBody', index: 1 },
    'sleepy':      { group: 'Idle',    index: 0 },
    'scared':      { group: 'TapBody', index: 2 },
    'sit_quietly': { group: 'Idle',    index: 0 },
    'think':       { group: 'Idle',    index: 0 }
};

// ========== 纯表情模型映射（无 motion 文件时使用） ==========
const EXPRESSION_ONLY_MAP = {
    'wave':        'happy',
    'nod_fast':    'happy',
    'shake':       'surprised',
    'bow':         'happy',
    'wave_arm':    'happy',
    'greet':       'happy',
    'happy':       'happy',
    'sad':         'sad',
    'angry':       'angry',
    'surprised':   'surprised',
    'sleepy':      'relaxed',
    'scared':      'surprised',
    'sit_quietly': 'relaxed',
    'think':       'neutral'
};

// ========== VRM 程序化骨骼动画库 ==========
const SKELETAL_ANIMATIONS = {
    wave: {
        duration: 2.0,
        bones: [{
            name: 'leftUpperArm',
            keys: [
                { time: 0.0, z: 0 },
                { time: 0.3, z: -0.8 },
                { time: 0.6, z: -0.3 },
                { time: 0.9, z: -0.8 },
                { time: 1.2, z: -0.3 },
                { time: 1.5, z: -0.8 },
                { time: 2.0, z: 0 }
            ]
        }, {
            name: 'leftLowerArm',
            keys: [
                { time: 0.0, z: 0 },
                { time: 0.3, z: -0.5 },
                { time: 0.6, z: -0.2 },
                { time: 0.9, z: -0.5 },
                { time: 1.2, z: -0.2 },
                { time: 1.5, z: -0.5 },
                { time: 2.0, z: 0 }
            ]
        }]
    },

    nod_fast: {
        duration: 1.0,
        bones: [{
            name: 'head',
            keys: [
                { time: 0.0, x: 0 },
                { time: 0.15, x: 0.25 },
                { time: 0.3, x: 0 },
                { time: 0.45, x: 0.25 },
                { time: 0.6, x: 0 },
                { time: 0.75, x: 0.15 },
                { time: 1.0, x: 0 }
            ]
        }]
    },

    shake: {
        duration: 1.5,
        bones: [{
            name: 'head',
            keys: [
                { time: 0.0, y: 0 },
                { time: 0.2, y: 0.2 },
                { time: 0.4, y: -0.2 },
                { time: 0.6, y: 0.15 },
                { time: 0.8, y: -0.15 },
                { time: 1.0, y: 0.08 },
                { time: 1.2, y: -0.08 },
                { time: 1.5, y: 0 }
            ]
        }]
    },

    bow: {
        duration: 2.5,
        bones: [{
            name: 'spine',
            keys: [
                { time: 0.0, x: 0 },
                { time: 0.8, x: 0.4 },
                { time: 1.5, x: 0.4 },
                { time: 2.5, x: 0 }
            ]
        }]
    },

    wave_arm: {
        duration: 2.0,
        bones: [{
            name: 'rightUpperArm',
            keys: [
                { time: 0.0, z: 0 },
                { time: 0.4, z: 0.8 },
                { time: 0.8, z: 0.4 },
                { time: 1.2, z: 0.8 },
                { time: 1.6, z: 0.4 },
                { time: 2.0, z: 0 }
            ]
        }]
    },

    greet: {
        duration: 2.0,
        bones: [{
            name: 'spine',
            keys: [
                { time: 0.0, x: 0 },
                { time: 0.5, x: 0.15 },
                { time: 1.5, x: 0.15 },
                { time: 2.0, x: 0 }
            ]
        }]
    },

    sit: {
        duration: 2.0,
        bones: [{
            name: 'leftUpperLeg',
            keys: [
                { time: 0.0, x: 0 },
                { time: 1.0, x: -1.2 },
                { time: 2.0, x: -1.2 }
            ]
        }, {
            name: 'rightUpperLeg',
            keys: [
                { time: 0.0, x: 0 },
                { time: 1.0, x: -1.2 },
                { time: 2.0, x: -1.2 }
            ]
        }, {
            name: 'leftLowerLeg',
            keys: [
                { time: 0.0, x: 0 },
                { time: 1.0, x: 1.5 },
                { time: 2.0, x: 1.5 }
            ]
        }, {
            name: 'rightLowerLeg',
            keys: [
                { time: 0.0, x: 0 },
                { time: 1.0, x: 1.5 },
                { time: 2.0, x: 1.5 }
            ]
        }, {
            name: 'spine',
            keys: [
                { time: 0.0, x: 0 },
                { time: 1.0, x: -0.1 },
                { time: 2.0, x: -0.1 }
            ]
        }]
    },

    wave_both: {
        duration: 2.5,
        bones: [{
            name: 'leftUpperArm',
            keys: [
                { time: 0.0, z: 0 },
                { time: 0.3, z: -0.9 },
                { time: 0.7, z: -0.4 },
                { time: 1.1, z: -0.9 },
                { time: 1.5, z: -0.4 },
                { time: 1.9, z: -0.9 },
                { time: 2.5, z: 0 }
            ]
        }, {
            name: 'rightUpperArm',
            keys: [
                { time: 0.0, z: 0 },
                { time: 0.5, z: 0.9 },
                { time: 0.9, z: 0.4 },
                { time: 1.3, z: 0.9 },
                { time: 1.7, z: 0.4 },
                { time: 2.1, z: 0.9 },
                { time: 2.5, z: 0 }
            ]
        }]
    },

    nod_slow: {
        duration: 2.0,
        bones: [{
            name: 'head',
            keys: [
                { time: 0.0, x: 0 },
                { time: 0.6, x: 0.15 },
                { time: 1.0, x: 0 },
                { time: 1.4, x: 0.15 },
                { time: 2.0, x: 0 }
            ]
        }]
    },

    head_tilt: {
        duration: 2.0,
        bones: [{
            name: 'head',
            keys: [
                { time: 0.0, x: 0, z: 0 },
                { time: 0.5, x: 0.1, z: 0.2 },
                { time: 1.5, x: 0.1, z: 0.2 },
                { time: 2.0, x: 0, z: 0 }
            ]
        }]
    },

    shoulder_shrug: {
        duration: 2.0,
        bones: [{
            name: 'leftUpperArm',
            keys: [
                { time: 0.0, z: 0 },
                { time: 0.4, z: -0.3 },
                { time: 1.2, z: -0.3 },
                { time: 2.0, z: 0 }
            ]
        }, {
            name: 'rightUpperArm',
            keys: [
                { time: 0.0, z: 0 },
                { time: 0.4, z: 0.3 },
                { time: 1.2, z: 0.3 },
                { time: 2.0, z: 0 }
            ]
        }, {
            name: 'spine',
            keys: [
                { time: 0.0, x: 0 },
                { time: 0.4, x: -0.05 },
                { time: 1.2, x: -0.05 },
                { time: 2.0, x: 0 }
            ]
        }]
    }
};

// 空闲动画定时器
let _idleInterval = null;
let _idleMs = 5000;

// ========== VRM 骨骼动画播放器 ==========
function playSkeletalAnimation(vrm, bones, duration) {
    if (!vrm || !vrm.scene) return;

    // 获取或创建 AnimationMixer
    let mixer = null;
    const engine = window.renderer && window.renderer.engines && window.renderer.engines.vrm;
    if (engine) {
        if (!engine.mixer) {
            engine.mixer = new THREE.AnimationMixer(vrm.scene);
        }
        mixer = engine.mixer;
    }
    if (!mixer) return;

    // 停止当前所有动画
    mixer.stopAllAction();

    const tracks = [];
    bones.forEach(function(boneConfig) {
        const boneNode = vrm.humanoid
            ? vrm.humanoid.getNormalizedBoneNode(boneConfig.name)
            : null;
        if (!boneNode) return;

        const times = [];
        const values = [];
        boneConfig.keys.forEach(function(key) {
            times.push(key.time);
            // 使用四元数：将欧拉角转换为四元数
            const euler = new THREE.Euler(
                key.x || 0,
                key.y || 0,
                key.z || 0,
                'XYZ'
            );
            const quat = new THREE.Quaternion().setFromEuler(euler);
            values.push(quat.x, quat.y, quat.z, quat.w);
        });

        const track = new THREE.QuaternionKeyframeTrack(
            boneNode.name + '.quaternion',
            times,
            values
        );
        tracks.push(track);
    });

    if (tracks.length === 0) return;

    const clip = new THREE.AnimationClip('procedural_' + Date.now(), duration, tracks);
    const action = mixer.clipAction(clip);
    action.setLoop(THREE.LoopOnce);
    action.clampWhenFinished = true;
    action.play();

    // 动画结束后重置姿态
    setTimeout(function() {
        action.stop();
        bones.forEach(function(boneConfig) {
            const boneNode = vrm.humanoid
                ? vrm.humanoid.getNormalizedBoneNode(boneConfig.name)
                : null;
            if (boneNode) {
                boneNode.quaternion.identity();
            }
        });
    }, duration * 1000 + 50);
}

// ========== Live2D Motion 播放（带映射） ==========
function playLive2DMotion(model, name) {
    if (!model) return;

    // 检测是否为纯表情模型（无 motion 定义）
    let isExpressionOnly = false;
    try {
        const mm = model.internalModel && model.internalModel.motionManager;
        if (!mm || !mm.definitions || Object.keys(mm.definitions).length === 0) {
            isExpressionOnly = true;
        }
    } catch (e) {
        isExpressionOnly = true;
    }

    if (isExpressionOnly) {
        // 纯表情模型：通过表情驱动（优先角色级映射）
        const exprMap = getEffectiveExpressionMap();
        const expr = exprMap[name] || 'happy';
        try {
            model.expression(expr);
            setTimeout(function() {
                try { model.expression(''); } catch(e) {}
            }, 2500);
            console.log('[Animation] Live2D expression-only:', expr);
        } catch (e) {
            console.warn('[Animation] Live2D expression-only error:', e.message);
        }
        return;
    }

    // 正常 motion 播放（优先角色级映射）
    const mapping = getEffectiveLive2DMotionMap()[name];
    if (!mapping) {
        // 没有映射，尝试表情降级
        tryLive2DExpressionFallback(model, name);
        return;
    }

    try {
        model.motion(mapping.group, mapping.index);
        console.log('[Animation] Live2D motion:', mapping.group, mapping.index);
    } catch (e) {
        console.warn('[Animation] Live2D motion error:', e.message);
        tryLive2DExpressionFallback(model, name);
    }
}

// Live2D 表情降级
function tryLive2DExpressionFallback(model, name) {
    const exprMap = getEffectiveExpressionMap();
    const fallbackNames = {
        'happy': 'happy', 'joy': 'happy',
        'sad': 'sad', 'upset': 'sad',
        'surprised': 'surprised', 'scared': 'surprised',
        'angry': 'angry',
        'sleepy': 'relaxed', 'sit_quietly': 'relaxed',
        'think': 'neutral'
    };
    const semanticName = fallbackNames[name] || name;
    const expr = exprMap[semanticName] || exprMap[name];
    if (!expr) return;
    try {
        model.expression(expr);
        setTimeout(function() {
            try { model.expression(''); } catch(e) {}
        }, 2000);
    } catch (e) {
        console.warn('[Animation] Live2D expression fallback error:', e.message);
    }
}

/**
 * 播放动作/表情
 * @param {string} name - 动作名称（语义名）
 * @param {string} group - 动作组（Live2D 用，可选）
 */
window.playMotion = (name, group) => {
    console.log('[Animation] playMotion:', name, group || '');

    const renderer = window.renderer;
    if (!renderer) return;

    // Fallback 头像动画反应
    if (typeof fallbackReaction === 'function') {
        fallbackReaction(name);
    }

    // VRM 骨骼动画 + 表情
    if (renderer.engines.vrm && renderer.engines.vrm.currentModel) {
        const vrm = renderer.engines.vrm.currentModel;
        const animCtrl = renderer.engines.vrm.animCtrl;

        // 优先使用外部动画文件
        if (animCtrl && animCtrl.clipCache.has(name)) {
            animCtrl.play(name);
            console.log('[Animation] VRM external anim:', name);
        } else {
            // 回退到程序化动画
            const mapping = MOTION_MAP[name] || MOTION_MAP['happy'];

            if (mapping.type === 'skeletal' && SKELETAL_ANIMATIONS[mapping.anim]) {
                const anim = SKELETAL_ANIMATIONS[mapping.anim];
                playSkeletalAnimation(vrm, anim.bones, anim.duration);
                console.log('[Animation] VRM skeletal:', mapping.anim);
            }
            if (mapping.type === 'expression' && vrm.expressionManager) {
                try {
                    vrm.expressionManager.setValue(mapping.name, 1.0);
                    setTimeout(() => {
                        vrm.expressionManager.setValue(mapping.name, 0);
                    }, 2000);
                    console.log('[Animation] VRM expression:', mapping.name);
                } catch (e) {
                    console.warn('[Animation] VRM expression error:', e.message);
                }
            }
        }
    }

    // Live2D 动作（使用映射）
    if (renderer.engines.live2d && renderer.engines.live2d.currentModel) {
        playLive2DMotion(renderer.engines.live2d.currentModel, name);
    }
};

/**
 * 设置表情
 * @param {string} name - 表情名称
 */
window.setExpression = (name) => {
    console.log('[Animation] setExpression:', name);

    const renderer = window.renderer;
    if (!renderer) return;

    // VRM 表情
    if (renderer.engines.vrm && renderer.engines.vrm.currentModel) {
        const vrm = renderer.engines.vrm.currentModel;
        if (vrm.expressionManager) {
            try {
                vrm.expressionManager.setValue(name, 1.0);
                setTimeout(() => {
                    vrm.expressionManager.setValue(name, 0);
                }, 1500);
            } catch (e) {
                console.warn('[Animation] VRM expression error:', e.message);
            }
        }
    }

    // Live2D 表情
    if (renderer.engines.live2d && renderer.engines.live2d.currentModel) {
        const model = renderer.engines.live2d.currentModel;
        try {
            model.expression(name);
        } catch (e) {
            console.warn('[Animation] Live2D expression error:', e.message);
        }
    }
};

/**
 * 播放随机动作
 */
window.playRandomMotion = () => {
    const motions = ['happy', 'surprised', 'sad', 'joy'];
    const randomMotion = motions[Math.floor(Math.random() * motions.length)];
    window.playMotion(randomMotion);
};

/**
 * 鼠标跟随
 * @param {number} x - 鼠标 X 坐标
 * @param {number} y - 鼠标 Y 坐标
 */
window.setMouseFollow = (x, y) => {
    const renderer = window.renderer;
    if (!renderer) return;

    // VRM LookAt
    if (renderer.engines.vrm && renderer.engines.vrm.currentModel) {
        const vrm = renderer.engines.vrm.currentModel;
        if (vrm.lookAt && vrm.lookAt.target) {
            const targetX = (x / window.innerWidth - 0.5) * 2;
            const targetY = (y / window.innerHeight - 0.5) * 2;
            vrm.lookAt.target.position.set(targetX * 0.5, targetY * 0.5 + 1.3, 2);
        }
    }

    // Live2D 鼠标跟随
    if (renderer.engines.live2d && renderer.engines.live2d.currentModel) {
        const model = renderer.engines.live2d.currentModel;
        if (model.focus) {
            model.focus(x, y);
        }
    }
};

/**
 * 启动空闲动画定时器
 * @param {number} intervalMs - 间隔毫秒
 */
window.startIdleTimer = (intervalMs) => {
    window.stopIdleTimer();
    _idleMs = intervalMs || 5000;
    _idleInterval = setInterval(() => {
        window.playRandomMotion();
    }, _idleMs);
    console.log('[Animation] Idle timer started:', _idleMs, 'ms');
};

/**
 * 停止空闲动画定时器
 */
window.stopIdleTimer = () => {
    if (_idleInterval) {
        clearInterval(_idleInterval);
        _idleInterval = null;
        console.log('[Animation] Idle timer stopped');
    }
};

/**
 * 设置模型缩放
 * @param {number} scale - 缩放比例
 */
window.setModelScale = (scale) => {
    const renderer = window.renderer;
    if (!renderer) return;

    // VRM 缩放
    if (renderer.engines.vrm && renderer.engines.vrm.currentModel) {
        const vrm = renderer.engines.vrm.currentModel;
        if (vrm.scene) {
            vrm.scene.scale.set(scale, scale, scale);
        }
    }

    // Live2D 缩放
    if (renderer.engines.live2d && renderer.engines.live2d.currentModel) {
        const model = renderer.engines.live2d.currentModel;
        model.scale.set(scale);
    }

    console.log('[Animation] Model scale:', scale);
};

/**
 * 加载动画文件（由 Python 端调用）
 * @param {Object} animConfig - { "idle": "idle.glb", "walk": "walk.bvh", ... }
 * @param {string} baseUrl - 动画文件所在目录的 URL
 * @returns {Promise<number>} 成功加载的数量
 */
window.loadAnimations = async (animConfig, baseUrl) => {
    const renderer = window.renderer;
    if (!renderer || !renderer.engines.vrm || !renderer.engines.vrm.animCtrl) {
        console.warn('[Animation] No VRM AnimationController available');
        return 0;
    }
    const count = await renderer.engines.vrm.animCtrl.loadAll(animConfig, baseUrl);
    console.log('[Animation] Loaded', count, 'animations from', baseUrl);
    return count;
};

/**
 * 停止当前动画
 * @param {number} fadeOut - 淡出时间（秒）
 */
window.stopAnimation = (fadeOut) => {
    const renderer = window.renderer;
    if (!renderer || !renderer.engines.vrm || !renderer.engines.vrm.animCtrl) return;
    renderer.engines.vrm.animCtrl.stop(fadeOut || 0);
};

/**
 * 获取动画系统状态
 * @returns {Object}
 */
window.getAnimationStats = () => {
    const renderer = window.renderer;
    const stats = { external: null, procedural: Object.keys(SKELETAL_ANIMATIONS) };
    if (renderer && renderer.engines.vrm && renderer.engines.vrm.animCtrl) {
        stats.external = renderer.engines.vrm.animCtrl.getCacheStats();
    }
    return stats;
};

console.log('[Renderer] Animation controls loaded');
console.log('[Renderer] Unified renderer loaded');
