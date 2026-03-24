import { app } from "../../scripts/app.js";

app.registerExtension({
    name: "Wudd.MultiSaveSafe",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "WuddMultiSaveImage") {
            
            // 1. 安全的连线逻辑
            const onConnectionsChange = nodeType.prototype.onConnectionsChange;
            nodeType.prototype.onConnectionsChange = function (type, index, connected) {
                if (onConnectionsChange) {
                    onConnectionsChange.apply(this, arguments);
                }
                if (type === 1 && this.inputs) {
                    try {
                        if (connected && index === this.inputs.length - 1) {
                            this.addInput("image_" + (this.inputs.length + 1), "IMAGE");
                        }
                        if (!connected && this.inputs.length > 1) {
                            while (this.inputs.length > 1 && !this.inputs[this.inputs.length - 1].link && !this.inputs[this.inputs.length - 2].link) {
                                this.removeInput(this.inputs.length - 1);
                            }
                        }
                    } catch (e) {
                        console.error("Wudd Ports Error:", e);
                    }
                }
            };

            // 2. 安全的显隐逻辑与回调修复
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) {
                    onNodeCreated.apply(this, arguments);
                }
                
                try {
                    const extWidget = this.widgets?.find(w => w.name === "extension");
                    const targetNames = ["quality", "progressive", "enable_xyb"];
                    
                    const refresh = () => {
                        const isJpegli = extWidget?.value === "jpegli";
                        this.widgets?.forEach(w => {
                            if (targetNames.includes(w.name)) {
                                w.type = isJpegli ? (w.name === "quality" ? "number" : "toggle") : "hidden";
                                // 标准的隐藏组件方法，防止 UI 出现空白缝隙
                                if (w.type === "hidden") {
                                    w.computeSize = () => [0, -4];
                                } else {
                                    delete w.computeSize;
                                }
                            }
                        });
                        // 刷新后让节点重新计算自身高度
                        if (this.setSize && this.computeSize) {
                            this.setSize(this.computeSize());
                        }
                    };

                    if (extWidget) {
                        const origCallback = extWidget.callback; 
                        extWidget.callback = function() {
                            refresh(); 
                            if (origCallback) {
                                return origCallback.apply(this, arguments); 
                            }
                        };
                        // 稍微延迟一下触发初始状态的刷新
                        setTimeout(refresh, 50);
                    }
                } catch (e) {
                    console.error("Wudd Widget Error:", e);
                }
            };
        }
    }
});