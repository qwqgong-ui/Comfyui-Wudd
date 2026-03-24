import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "Wudd.MultiSaveSafe",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "WuddMultiSaveImage") {
            
            // ==========================================
            // 1. 极致安全的动态端口逻辑 (防死循环、完美兼容复制)
            // ==========================================
            const onConnectionsChange = nodeType.prototype.onConnectionsChange;
            nodeType.prototype.onConnectionsChange = function (type, index, connected, link_info) {
                if (onConnectionsChange) onConnectionsChange.apply(this, arguments);
                
                if (this.__isUpdatingPorts) return;
                this.__isUpdatingPorts = true;
                
                // type 1 代表 INPUT。确保只处理输入端口的连线
                if (type === 1 && this.inputs && this.inputs.length > 0) {
                    try {
                        // 逻辑 A：清理尾部多余的空闲端口 (始终保持最后只有 1 个空端口)
                        while (this.inputs.length > 1 && 
                               !this.inputs[this.inputs.length - 1].link && 
                               !this.inputs[this.inputs.length - 2].link) {
                            this.removeInput(this.inputs.length - 1);
                        }
                        
                        // 逻辑 B：如果最后一个端口被连上了，就自动新增一个空端口
                        const lastInput = this.inputs[this.inputs.length - 1];
                        if (lastInput && lastInput.link) {
                            this.addInput("image_" + (this.inputs.length + 1), "IMAGE");
                        }
                    } catch (e) { 
                        console.error("Wudd Ports Error:", e); 
                    }
                }
                
                this.__isUpdatingPorts = false;
            };

            // ==========================================
            // 2. 极致安全的组件显隐逻辑 (防复制卡死版)
            // ==========================================
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);
                
                try {
                    const extWidget = this.widgets?.find(w => w.name === "extension");
                    const targetNames = ["quality", "progressive", "enable_xyb", "chroma_subsampling"];
                    
                    const refresh = () => {
                        if (!this.widgets) return;
                        const isJpegli = extWidget?.value === "jpegli";
                        let visibilityChanged = false; // 增加状态锁：只在状态真发生改变时才重绘

                        this.widgets.forEach(w => {
                            if (targetNames.includes(w.name)) {
                                // 初始化并缓存原生属性
                                if (w.origType === undefined) {
                                    w.origType = w.type;
                                    w.origComputeSize = w.computeSize;
                                }
                                
                                if (isJpegli) {
                                    if (w.type !== w.origType) {
                                        w.type = w.origType;
                                        w.computeSize = w.origComputeSize;
                                        visibilityChanged = true;
                                    }
                                } else {
                                    if (w.type !== "hidden") {
                                        w.type = "hidden";
                                        w.computeSize = () => [0, -4];
                                        visibilityChanged = true;
                                    }
                                }
                            }
                        });
                        
                        // 【核心修复】：将尺寸计算推迟到引擎克隆生命周期结束之后，避开死锁！
                        if (visibilityChanged && this.setSize && this.computeSize) {
                            setTimeout(() => {
                                try {
                                    this.setSize(this.computeSize());
                                    if (this.setDirtyCanvas) this.setDirtyCanvas(true, true);
                                } catch(e) {}
                            }, 10);
                        }
                    };

                    if (extWidget) {
                        const origCallback = extWidget.callback; 
                        extWidget.callback = function() {
                            refresh(); 
                            if (origCallback) return origCallback.apply(this, arguments); 
                        };
                        // 初始化时也异步执行，确保节点已经安全挂载
                        setTimeout(refresh, 50);
                    }
                } catch (e) { 
                    console.error("Wudd Widget Error:", e); 
                }
            };
        }
    }
});