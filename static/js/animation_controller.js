/**
 * AnimationController - VRM 动画加载与播放控制器
 * 支持：GLB 动画加载、BVH 解析、Mixamo 骨骼重定向、缓存池、crossFade 过渡
 */

// ========== Mixamo → VRM 骨骼名映射表 ==========
const MIXAMO_TO_VRM_BONE_MAP = {
    'mixamorig:Hips':          'hips',
    'mixamorig:Spine':         'spine',
    'mixamorig:Spine1':        'chest',
    'mixamorig:Spine2':        'upperChest',
    'mixamorig:Neck':          'neck',
    'mixamorig:Head':          'head',

    'mixamorig:LeftShoulder':  'leftShoulder',
    'mixamorig:LeftUpperArm':  'leftUpperArm',
    'mixamorig:LeftLowerArm':  'leftLowerArm',
    'mixamorig:LeftHand':      'leftHand',

    'mixamorig:RightShoulder': 'rightShoulder',
    'mixamorig:RightUpperArm': 'rightUpperArm',
    'mixamorig:RightLowerArm': 'rightLowerArm',
    'mixamorig:RightHand':     'rightHand',

    'mixamorig:LeftUpperLeg':  'leftUpperLeg',
    'mixamorig:LeftLowerLeg':  'leftLowerLeg',
    'mixamorig:LeftFoot':      'leftFoot',
    'mixamorig:LeftToeBase':   'leftToes',

    'mixamorig:RightUpperLeg': 'rightUpperLeg',
    'mixamorig:RightLowerLeg': 'rightLowerLeg',
    'mixamorig:RightFoot':     'rightFoot',
    'mixamorig:RightToeBase':  'rightToes',

    'mixamorig:LeftHandThumb1':  'leftThumbProximal',
    'mixamorig:LeftHandThumb2':  'leftThumbIntermediate',
    'mixamorig:LeftHandThumb3':  'leftThumbDistal',
    'mixamorig:LeftHandIndex1':  'leftIndexProximal',
    'mixamorig:LeftHandIndex2':  'leftIndexIntermediate',
    'mixamorig:LeftHandIndex3':  'leftIndexDistal',
    'mixamorig:LeftHandMiddle1': 'leftMiddleProximal',
    'mixamorig:LeftHandMiddle2': 'leftMiddleIntermediate',
    'mixamorig:LeftHandMiddle3': 'leftMiddleDistal',

    'mixamorig:RightHandThumb1':  'rightThumbProximal',
    'mixamorig:RightHandThumb2':  'rightThumbIntermediate',
    'mixamorig:RightHandThumb3':  'rightThumbDistal',
    'mixamorig:RightHandIndex1':  'rightIndexProximal',
    'mixamorig:RightHandIndex2':  'rightIndexIntermediate',
    'mixamorig:RightHandIndex3':  'rightIndexDistal',
    'mixamorig:RightHandMiddle1': 'rightMiddleProximal',
    'mixamorig:RightHandMiddle2': 'rightMiddleIntermediate',
    'mixamorig:RightHandMiddle3': 'rightMiddleDistal'
};

// 无前缀版本（部分工具导出的 FBX 不带 mixamorig: 前缀）
const SHORT_TO_VRM_BONE_MAP = {
    'Hips':          'hips',
    'Spine':         'spine',
    'Spine1':        'chest',
    'Spine2':        'upperChest',
    'Neck':          'neck',
    'Head':          'head',
    'LeftShoulder':  'leftShoulder',
    'LeftUpperArm':  'leftUpperArm',
    'LeftLowerArm':  'leftLowerArm',
    'LeftHand':      'leftHand',
    'RightShoulder': 'rightShoulder',
    'RightUpperArm': 'rightUpperArm',
    'RightLowerArm': 'rightLowerArm',
    'RightHand':     'rightHand',
    'LeftUpperLeg':  'leftUpperLeg',
    'LeftLowerLeg':  'leftLowerLeg',
    'LeftFoot':      'leftFoot',
    'LeftToeBase':   'leftToes',
    'RightUpperLeg': 'rightUpperLeg',
    'RightLowerLeg': 'rightLowerLeg',
    'RightFoot':     'rightFoot',
    'RightToeBase':  'rightToes'
};

// 合并为统一映射
const BONE_NAME_MAP = Object.assign({}, MIXAMO_TO_VRM_BONE_MAP, SHORT_TO_VRM_BONE_MAP);


// ========== BVH 解析器 ==========
class BVHParser {
    /**
     * 解析 BVH 文本为动画数据
     * @param {string} text - BVH 文件内容
     * @returns {Object} { hierarchy, frames, frameTime, jointNames }
     */
    static parse(text) {
        const lines = text.split(/\r?\n/);
        let i = 0;
        const hierarchy = { name: 'root', type: '', offset: [0, 0, 0], channels: [], children: [] };

        // 解析 HIERARCHY
        function parseJoint(parent) {
            while (i < lines.length) {
                const line = lines[i++].trim();
                if (line === '{') {
                    continue;
                } else if (line === '}') {
                    return;
                } else if (line.startsWith('ROOT') || line.startsWith('JOINT')) {
                    const parts = line.split(/\s+/);
                    const joint = {
                        name: parts[1],
                        type: parts[0] === 'ROOT' ? 'root' : 'joint',
                        offset: [0, 0, 0],
                        channels: [],
                        children: []
                    };
                    parent.children.push(joint);
                    parseJoint(joint);
                } else if (line.startsWith('End Site')) {
                    const endSite = { name: parent.name + '_end', type: 'end', offset: [0, 0, 0], channels: [], children: [] };
                    parent.children.push(endSite);
                    // 读取 { offset x y z }
                    while (i < lines.length) {
                        const el = lines[i++].trim();
                        if (el === '}') break;
                        if (el.startsWith('OFFSET')) {
                            const p = el.split(/\s+/);
                            endSite.offset = [parseFloat(p[1]), parseFloat(p[2]), parseFloat(p[3])];
                        }
                    }
                } else if (line.startsWith('OFFSET')) {
                    const parts = line.split(/\s+/);
                    parent.offset = [parseFloat(parts[1]), parseFloat(parts[2]), parseFloat(parts[3])];
                } else if (line.startsWith('CHANNELS')) {
                    const parts = line.split(/\s+/);
                    const numChannels = parseInt(parts[1]);
                    parent.channels = parts.slice(2, 2 + numChannels);
                }
            }
        }

        // 找到 HIERARCHY
        while (i < lines.length && !lines[i].trim().startsWith('HIERARCHY')) i++;
        i++; // skip HIERARCHY line
        parseJoint(hierarchy);

        // 解析 MOTION
        let numFrames = 0;
        let frameTime = 1 / 30;
        const frames = [];

        while (i < lines.length) {
            const line = lines[i++].trim();
            if (line.startsWith('Frames:')) {
                numFrames = parseInt(line.split(/\s+/)[1]);
            } else if (line.startsWith('Frame Time:')) {
                frameTime = parseFloat(line.split(/\s+/)[2]);
            } else if (line && !isNaN(parseFloat(line.split(/\s+/)[0]))) {
                frames.push(line.split(/\s+/).map(Number));
            }
        }

        // 收集所有关节名
        const jointNames = [];
        function collectNames(node) {
            if (node.type !== 'end') jointNames.push(node.name);
            node.children.forEach(child => collectNames(child));
        }
        collectNames(hierarchy);

        return { hierarchy, frames, frameTime, jointNames, numFrames };
    }

    /**
     * 将 BVH 数据转换为 THREE.AnimationClip
     * @param {Object} bvhData - BVHParser.parse() 的输出
     * @param {Object} vrmHumanoid - VRM humanoid 实例
     * @returns {THREE.AnimationClip}
     */
    static toAnimationClip(bvhData, vrmHumanoid) {
        const { hierarchy, frames, frameTime, jointNames, numFrames } = bvhData;
        const tracks = [];

        // 收集每个关节的通道信息
        const jointChannelMap = {};
        function mapChannels(node) {
            if (node.type !== 'end') {
                jointChannelMap[node.name] = {
                    channels: node.channels,
                    offset: node.offset
                };
            }
            node.children.forEach(child => mapChannels(child));
        }
        mapChannels(hierarchy);

        // 为每个关节创建关键帧轨道
        let channelOffset = 0;
        for (const jointName of jointNames) {
            const info = jointChannelMap[jointName];
            if (!info) { channelOffset += 6; continue; }

            // 映射到 VRM 骨骼名
            const vrmBoneName = BONE_NAME_MAP[jointName] || BONE_NAME_MAP['mixamorig:' + jointName] || jointName.toLowerCase();

            // 获取 VRM 骨骼节点
            const boneNode = vrmHumanoid ? vrmHumanoid.getNormalizedBoneNode(vrmBoneName) : null;
            if (!boneNode) {
                channelOffset += info.channels.length;
                continue;
            }

            // 提取旋转通道（Zrotation, Xrotation, Yrotation 或 Xrotation, Yrotation, Zrotation）
            const hasRotation = info.channels.some(c => c.includes('rotation'));
            const hasPosition = info.channels.some(c => c.includes('position'));

            if (hasRotation) {
                const times = [];
                const values = [];

                // 找到旋转通道的索引
                const rotChannels = info.channels.filter(c => c.includes('rotation'));
                const rotIndices = rotChannels.map(c => info.channels.indexOf(c));

                for (let f = 0; f < numFrames; f++) {
                    times.push(f * frameTime);

                    // 提取欧拉角（度数 → 弧度）
                    const euler = [0, 0, 0];
                    rotIndices.forEach((idx, i) => {
                        const deg = frames[f] ? frames[f][channelOffset + idx] : 0;
                        euler[i] = deg * Math.PI / 180;
                    });

                    // BVH 旋转顺序通常是 ZXY
                    const q = new THREE.Quaternion();
                    const eulerObj = new THREE.Euler(euler[0], euler[1], euler[2], 'ZXY');
                    q.setFromEuler(eulerObj);
                    values.push(q.x, q.y, q.z, q.w);
                }

                tracks.push(new THREE.QuaternionKeyframeTrack(
                    boneNode.name + '.quaternion',
                    times,
                    values
                ));
            }

            channelOffset += info.channels.length;
        }

        if (tracks.length === 0) return null;
        return new THREE.AnimationClip('bvh_' + Date.now(), numFrames * frameTime, tracks);
    }
}


// ========== 动画控制器 ==========
class AnimationController {
    /**
     * @param {THREE.Scene} scene - Three.js 场景
     * @param {Object} vrm - VRM 模型实例
     */
    constructor(scene, vrm) {
        this.scene = scene;
        this.vrm = vrm;
        this.mixer = null;
        this.currentAction = null;
        this.previousAction = null;
        this.clipCache = new Map();  // { name: AnimationClip }
        this.fileCache = new Map();  // { url: ArrayBuffer/Text }
        this.loader = null;
        this.isPlaying = false;
        this._updateCallback = null;
        this._blendDuration = 0.3;  // 默认过渡时间（秒）
    }

    /**
     * 初始化（需要 THREE 和 GLTFLoader 已加载）
     */
    init() {
        if (!this.vrm || !this.vrm.scene) {
            console.warn('[AnimCtrl] No VRM model');
            return false;
        }
        this.mixer = new THREE.AnimationMixer(this.vrm.scene);

        if (typeof THREE.GLTFLoader !== 'undefined') {
            this.loader = new THREE.GLTFLoader();
            // 注册 VRM 插件
            if (typeof THREE_VRM !== 'undefined' && THREE_VRM.VRMLoaderPlugin) {
                this.loader.register(function(parser) {
                    return new THREE_VRM.VRMLoaderPlugin(parser);
                });
            }
        }

        console.log('[AnimCtrl] Initialized');
        return true;
    }

    /**
     * 设置过渡时间
     * @param {number} duration - 秒
     */
    setBlendDuration(duration) {
        this._blendDuration = Math.max(0, duration);
    }

    /**
     * 更新 mixer（每帧调用）
     * @param {number} deltaTime - 秒
     */
    update(deltaTime) {
        if (this.mixer) {
            this.mixer.update(deltaTime);
        }
    }

    // ========== 动画加载 ==========

    /**
     * 从 GLB 文件加载动画
     * @param {string} name - 动画名称（用于缓存键）
     * @param {string} url - GLB 文件路径
     * @returns {Promise<THREE.AnimationClip|null>}
     */
    async loadGLB(name, url) {
        // 检查缓存
        if (this.clipCache.has(name)) {
            console.log('[AnimCtrl] Cache hit:', name);
            return this.clipCache.get(name);
        }

        if (!this.loader) {
            console.error('[AnimCtrl] GLTFLoader not available');
            return null;
        }

        try {
            console.log('[AnimCtrl] Loading GLB:', url);
            const gltf = await this._loadGLTFAsync(url);

            if (gltf.animations && gltf.animations.length > 0) {
                const clip = gltf.animations[0];
                this._retargetClip(clip);
                this.clipCache.set(name, clip);
                console.log('[AnimCtrl] GLB loaded:', name, 'duration:', clip.duration.toFixed(2) + 's');
                return clip;
            } else {
                console.warn('[AnimCtrl] No animations in GLB:', url);
                return null;
            }
        } catch (e) {
            console.error('[AnimCtrl] GLB load error:', e.message);
            return null;
        }
    }

    /**
     * 从 BVH 文件加载动画
     * @param {string} name - 动画名称
     * @param {string} url - BVH 文件路径
     * @returns {Promise<THREE.AnimationClip|null>}
     */
    async loadBVH(name, url) {
        if (this.clipCache.has(name)) {
            return this.clipCache.get(name);
        }

        try {
            console.log('[AnimCtrl] Loading BVH:', url);
            const text = await this._fetchText(url);
            const bvhData = BVHParser.parse(text);
            const clip = BVHParser.toAnimationClip(bvhData, this.vrm ? this.vrm.humanoid : null);

            if (clip) {
                this.clipCache.set(name, clip);
                console.log('[AnimCtrl] BVH loaded:', name, 'duration:', clip.duration.toFixed(2) + 's');
                return clip;
            }
            return null;
        } catch (e) {
            console.error('[AnimCtrl] BVH load error:', e.message);
            return null;
        }
    }

    /**
     * 从 JSON 文件加载动画（自定义格式）
     * @param {string} name - 动画名称
     * @param {string} url - JSON 文件路径
     * @returns {Promise<THREE.AnimationClip|null>}
     */
    async loadJSON(name, url) {
        if (this.clipCache.has(name)) {
            return this.clipCache.get(name);
        }

        try {
            console.log('[AnimCtrl] Loading JSON animation:', url);
            const data = await this._fetchJSON(url);
            const clip = this._parseCustomJSON(data);

            if (clip) {
                this.clipCache.set(name, clip);
                console.log('[AnimCtrl] JSON loaded:', name, 'duration:', clip.duration.toFixed(2) + 's');
                return clip;
            }
            return null;
        } catch (e) {
            console.error('[AnimCtrl] JSON load error:', e.message);
            return null;
        }
    }

    /**
     * 根据文件扩展名自动选择加载方式
     * @param {string} name - 动画名称
     * @param {string} url - 文件路径
     * @returns {Promise<THREE.AnimationClip|null>}
     */
    async load(name, url) {
        const ext = url.split('.').pop().toLowerCase().split('?')[0];
        switch (ext) {
            case 'glb':
            case 'gltf':
                return this.loadGLB(name, url);
            case 'bvh':
                return this.loadBVH(name, url);
            case 'json':
                return this.loadJSON(name, url);
            default:
                console.error('[AnimCtrl] Unsupported format:', ext);
                return null;
        }
    }

    /**
     * 批量加载动画配置
     * @param {Object} animConfig - { "idle": "idle.glb", "walk": "walk.bvh", ... }
     * @param {string} baseUrl - 基础路径
     * @returns {Promise<number>} 成功加载的数量
     */
    async loadAll(animConfig, baseUrl) {
        let loaded = 0;
        const tasks = Object.entries(animConfig).map(async ([name, path]) => {
            const url = baseUrl ? baseUrl + '/' + path : path;
            const clip = await this.load(name, url);
            if (clip) loaded++;
        });
        await Promise.all(tasks);
        console.log('[AnimCtrl] Batch loaded:', loaded, '/', Object.keys(animConfig).length);
        return loaded;
    }

    // ========== 动画播放 ==========

    /**
     * 播放动画（带 crossFade 过渡）
     * @param {string} name - 动画名称
     * @param {Object} options - { loop, crossFadeDuration, timeScale, weight }
     * @returns {boolean} 是否成功
     */
    play(name, options = {}) {
        const clip = this.clipCache.get(name);
        if (!clip) {
            console.warn('[AnimCtrl] Animation not found:', name);
            return false;
        }

        const {
            loop = true,
            crossFadeDuration = this._blendDuration,
            timeScale = 1.0,
            weight = 1.0
        } = options;

        const newAction = this.mixer.clipAction(clip);
        newAction.reset();
        newAction.setLoop(loop ? THREE.LoopRepeat : THREE.LoopOnce);
        newAction.clampWhenFinished = !loop;
        newAction.timeScale = timeScale;
        newAction.weight = weight;

        if (this.currentAction && this.currentAction !== newAction && crossFadeDuration > 0) {
            // crossFade 过渡
            this.currentAction.crossFadeTo(newAction, crossFadeDuration);
            newAction.play();
        } else {
            // 直接播放
            if (this.currentAction) this.currentAction.stop();
            newAction.play();
        }

        this.previousAction = this.currentAction;
        this.currentAction = newAction;
        this.isPlaying = true;

        // 非循环动画结束时的回调
        if (!loop) {
            const onFinished = () => {
                this.mixer.removeEventListener('finished', onFinished);
                if (this.currentAction === newAction) {
                    this.isPlaying = false;
                }
            };
            this.mixer.addEventListener('finished', onFinished);
        }

        console.log('[AnimCtrl] Playing:', name, 'loop:', loop, 'fade:', crossFadeDuration + 's');
        return true;
    }

    /**
     * 停止当前动画
     * @param {number} fadeOutDuration - 淡出时间（秒），0 = 立即停止
     */
    stop(fadeOutDuration = 0) {
        if (!this.currentAction) return;

        if (fadeOutDuration > 0) {
            this.currentAction.fadeOut(fadeOutDuration);
            setTimeout(() => {
                if (this.currentAction) {
                    this.currentAction.stop();
                    this.currentAction = null;
                }
                this.isPlaying = false;
            }, fadeOutDuration * 1000);
        } else {
            this.currentAction.stop();
            this.currentAction = null;
            this.isPlaying = false;
        }
    }

    /**
     * 暂停当前动画
     */
    pause() {
        if (this.currentAction) {
            this.currentAction.paused = true;
            this.isPlaying = false;
        }
    }

    /**
     * 恢复暂停的动画
     */
    resume() {
        if (this.currentAction) {
            this.currentAction.paused = false;
            this.isPlaying = true;
        }
    }

    /**
     * 获取当前动画名称
     * @returns {string|null}
     */
    getCurrentAnimationName() {
        if (!this.currentAction) return null;
        for (const [name, clip] of this.clipCache) {
            if (this.currentAction.getClip() === clip) return name;
        }
        return null;
    }

    /**
     * 获取已缓存的动画列表
     * @returns {string[]}
     */
    getLoadedAnimations() {
        return Array.from(this.clipCache.keys());
    }

    /**
     * 获取缓存统计
     * @returns {Object}
     */
    getCacheStats() {
        return {
            cachedClips: this.clipCache.size,
            cachedFiles: this.fileCache.size,
            currentAnimation: this.getCurrentAnimationName(),
            isPlaying: this.isPlaying
        };
    }

    // ========== 内部方法 ==========

    /**
     * 重定向动画轨道的骨骼名（Mixamo → VRM）
     */
    _retargetClip(clip) {
        clip.tracks.forEach(track => {
            // track.name 格式: "boneName.quaternion" 或 "boneName.position"
            const dotIndex = track.name.lastIndexOf('.');
            if (dotIndex === -1) return;

            const boneName = track.name.substring(0, dotIndex);
            const property = track.name.substring(dotIndex);

            const vrmName = BONE_NAME_MAP[boneName] || BONE_NAME_MAP['mixamorig:' + boneName];
            if (vrmName && vrmName !== boneName) {
                track.name = vrmName + property;
            }
        });
    }

    /**
     * 解析自定义 JSON 动画格式
     * JSON 格式: { "duration": 2.0, "bones": { "head": { "times": [0, 0.5, 1], "rotations": [[x,y,z,w], ...] }, ... } }
     */
    _parseCustomJSON(data) {
        if (!data || !data.bones) return null;

        const tracks = [];
        const duration = data.duration || 2.0;

        for (const [boneName, boneData] of Object.entries(data.bones)) {
            const vrmBoneName = BONE_NAME_MAP[boneName] || boneName;
            const boneNode = this.vrm && this.vrm.humanoid
                ? this.vrm.humanoid.getNormalizedBoneNode(vrmBoneName)
                : null;

            if (!boneNode) continue;

            if (boneData.rotations && boneData.times) {
                const values = [];
                boneData.rotations.forEach(q => {
                    values.push(q[0], q[1], q[2], q[3]);
                });
                tracks.push(new THREE.QuaternionKeyframeTrack(
                    boneNode.name + '.quaternion',
                    boneData.times,
                    values
                ));
            }

            if (boneData.positions && boneData.times) {
                const values = [];
                boneData.positions.forEach(p => {
                    values.push(p[0], p[1], p[2]);
                });
                tracks.push(new THREE.VectorKeyframeTrack(
                    boneNode.name + '.position',
                    boneData.times,
                    values
                ));
            }
        }

        if (tracks.length === 0) return null;
        return new THREE.AnimationClip('json_' + Date.now(), duration, tracks);
    }

    /**
     * Promise 包装 GLTFLoader.load
     */
    _loadGLTFAsync(url) {
        return new Promise((resolve, reject) => {
            // 优先用 XMLHttpRequest（兼容 file:/// 协议）
            const xhr = new XMLHttpRequest();
            xhr.open('GET', url, true);
            xhr.responseType = 'arraybuffer';

            xhr.onload = () => {
                if (xhr.status === 200 || xhr.status === 0) {
                    this.loader.parse(xhr.response, '', resolve, reject);
                } else {
                    reject(new Error('HTTP ' + xhr.status));
                }
            };
            xhr.onerror = () => reject(new Error('Network error'));
            xhr.send();
        });
    }

    /**
     * Promise 包装 fetch（兼容 file:///）
     */
    async _fetchText(url) {
        // 优先用 XMLHttpRequest 兼容 file:///
        return new Promise((resolve, reject) => {
            const xhr = new XMLHttpRequest();
            xhr.open('GET', url, true);
            xhr.responseType = 'text';
            xhr.onload = () => {
                if (xhr.status === 200 || xhr.status === 0) {
                    resolve(xhr.responseText);
                } else {
                    reject(new Error('HTTP ' + xhr.status));
                }
            };
            xhr.onerror = () => reject(new Error('Network error'));
            xhr.send();
        });
    }

    /**
     * Promise 包装 fetch JSON
     */
    async _fetchJSON(url) {
        const text = await this._fetchText(url);
        return JSON.parse(text);
    }

    /**
     * 清理资源
     */
    dispose() {
        if (this.mixer) {
            this.mixer.stopAllAction();
            this.mixer.uncacheRoot(this.vrm.scene);
            this.mixer = null;
        }
        this.clipCache.clear();
        this.fileCache.clear();
        this.currentAction = null;
        this.previousAction = null;
        this.isPlaying = false;
        console.log('[AnimCtrl] Disposed');
    }
}


// ========== 导出 ==========
window.AnimationController = AnimationController;
window.BVHParser = BVHParser;
window.BONE_NAME_MAP = BONE_NAME_MAP;
window.MIXAMO_TO_VRM_BONE_MAP = MIXAMO_TO_VRM_BONE_MAP;

console.log('[AnimCtrl] AnimationController loaded');
