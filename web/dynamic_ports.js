import { app } from "../../scripts/app.js";

const INPUT = 1;

function clampInt(value, min, max) {
    const n = Number.parseInt(value, 10);
    if (!Number.isFinite(n)) return min;
    return Math.max(min, Math.min(n, max));
}

function indexedSlotNumber(name, prefix) {
    const value = String(name || "");
    if (!value.startsWith(prefix)) return null;
    const n = Number.parseInt(value.slice(prefix.length), 10);
    return Number.isFinite(n) ? n : null;
}

function slotHasLink(slot) {
    return slot?.link != null || (Array.isArray(slot?.links) && slot.links.length > 0);
}

function highestLinkedIndex(slots, prefix) {
    let highest = 0;
    for (const slot of slots || []) {
        if (!slotHasLink(slot)) continue;
        const idx = indexedSlotNumber(slot.name, prefix);
        if (idx != null) highest = Math.max(highest, idx);
    }
    return highest;
}

function rememberWidget(widget) {
    if (!widget || widget.__wuddOriginalType !== undefined) return;
    widget.__wuddOriginalType = widget.origType ?? widget.type;
    widget.__wuddOriginalComputeSize = widget.origComputeSize ?? widget.computeSize;
    widget.origType ??= widget.__wuddOriginalType;
    widget.origComputeSize ??= widget.__wuddOriginalComputeSize;
}

function setWidgetVisible(widget, visible) {
    if (!widget) return false;
    rememberWidget(widget);

    if (visible) {
        if (widget.type !== widget.__wuddOriginalType) {
            widget.type = widget.__wuddOriginalType;
            widget.computeSize = widget.__wuddOriginalComputeSize;
            return true;
        }
        return false;
    }

    if (widget.type !== "hidden") {
        widget.type = "hidden";
        widget.computeSize = () => [0, -4];
        return true;
    }
    return false;
}

function refreshNode(node, defer = false) {
    const doRefresh = () => {
        if (node.setSize && node.computeSize) {
            try { node.setSize(node.computeSize()); } catch (e) {}
        }
        if (node.setDirtyCanvas) node.setDirtyCanvas(true, true);
        if (app.graph?.setDirtyCanvas) app.graph.setDirtyCanvas(true, true);
    };
    if (defer) setTimeout(doRefresh, 10);
    else doRefresh();
}

function wireCountWidget(node, widgetName, apply) {
    const countWidget = node.widgets?.find(w => w.name === widgetName);
    if (!countWidget) return;

    const origCallback = countWidget.callback;
    countWidget.callback = function () {
        apply();
        if (origCallback) return origCallback.apply(this, arguments);
    };

    setTimeout(apply, 50);
}

function syncOutputCount(node, countWidget, options) {
    const { max, prefix, type, firstIndex } = options;
    const requested = clampInt(countWidget?.value, 1, max);
    const linkedMin = highestLinkedIndex(node.outputs, prefix);
    const count = Math.max(requested, firstIndex === 0 ? linkedMin + 1 : linkedMin, 1);

    if (countWidget && countWidget.value !== count) {
        countWidget.value = count;
    }

    while (!node.outputs || node.outputs.length < count) {
        const idx = firstIndex + (node.outputs?.length || 0);
        node.addOutput(`${prefix}${idx}`, type);
    }

    while (node.outputs && node.outputs.length > count) {
        const last = node.outputs[node.outputs.length - 1];
        if (slotHasLink(last)) break;
        node.removeOutput(node.outputs.length - 1);
    }

    refreshNode(node);
}

function syncImageInputs(node, countWidget, options) {
    const { max, prefix, type } = options;
    const requested = clampInt(countWidget?.value, 1, max);
    const count = Math.max(requested, highestLinkedIndex(node.inputs, prefix), 1);

    if (countWidget && countWidget.value !== count) {
        countWidget.value = count;
    }

    for (let i = (node.inputs?.length || 0) - 1; i >= 0; i--) {
        const input = node.inputs[i];
        const idx = indexedSlotNumber(input?.name, prefix);
        if (idx != null && idx > count && !slotHasLink(input)) {
            node.removeInput(i);
        }
    }

    const existing = new Set((node.inputs || []).map(input => input.name));
    for (let i = 2; i <= count; i++) {
        const name = `${prefix}${i}`;
        if (!existing.has(name)) {
            node.addInput(name, type);
        }
    }

    refreshNode(node);
}

app.registerExtension({
    name: "Wudd.DynamicPorts",
    async beforeRegisterNodeDef(nodeType, nodeData) {

        // ==========================================
        // WuddMultiSaveImage — 动态输入端口
        // ==========================================
        if (nodeData.name === "WuddMultiSaveImage") {

            const onConnectionsChange = nodeType.prototype.onConnectionsChange;
            nodeType.prototype.onConnectionsChange = function (type, index, connected, link_info) {
                if (onConnectionsChange) onConnectionsChange.apply(this, arguments);

                if (this.__isUpdatingPorts) return;
                this.__isUpdatingPorts = true;

                if (type === INPUT && this.inputs && this.inputs.length > 0) {
                    try {
                        while (this.inputs.length > 1 &&
                               !this.inputs[this.inputs.length - 1].link &&
                               !this.inputs[this.inputs.length - 2].link) {
                            this.removeInput(this.inputs.length - 1);
                        }

                        const lastInput = this.inputs[this.inputs.length - 1];
                        if (lastInput?.link) {
                            this.addInput(`image_${this.inputs.length + 1}`, "IMAGE");
                        }
                    } catch (e) {
                        console.error("Wudd Ports Error:", e);
                    }
                }

                this.__isUpdatingPorts = false;
            };

            const COMBO_DEFAULTS = {
                save_mode:          { valid: ["append", "overwrite"],          def: "append" },
                extension:          { valid: ["png", "jpegli"],                def: "png"    },
                chroma_subsampling: { valid: ["444", "440", "422", "420"],     def: "444"    },
            };
            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (config) {
                if (onConfigure) onConfigure.apply(this, arguments);
                if (!this.widgets) return;
                this.widgets.forEach(w => {
                    const spec = COMBO_DEFAULTS[w.name];
                    if (spec && !spec.valid.includes(w.value)) {
                        console.warn(`[Wudd] widget "${w.name}" had invalid value "${w.value}", reset to "${spec.def}"`);
                        w.value = spec.def;
                    }
                });
            };

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);

                try {
                    const extWidget = this.widgets?.find(w => w.name === "extension");
                    const targetNames = new Set(["quality", "progressive", "enable_xyb", "chroma_subsampling"]);

                    const refresh = () => {
                        const isJpegli = extWidget?.value === "jpegli";
                        let changed = false;
                        for (const widget of this.widgets || []) {
                            if (targetNames.has(widget.name)) {
                                changed = setWidgetVisible(widget, isJpegli) || changed;
                            }
                        }
                        if (changed) refreshNode(this, true);
                    };

                    if (extWidget) {
                        const origCallback = extWidget.callback;
                        extWidget.callback = function () {
                            refresh();
                            if (origCallback) return origCallback.apply(this, arguments);
                        };
                        setTimeout(refresh, 50);
                    }
                } catch (e) {
                    console.error("Wudd Widget Error:", e);
                }
            };
        }

        // ==========================================
        // WuddMultiTextSplitter — 动态输出端口
        // ==========================================
        if (nodeData.name === "WuddMultiTextSplitter") {
            const applyOutputCount = node => {
                const countWidget = node.widgets?.find(w => w.name === "count");
                if (countWidget) {
                    syncOutputCount(node, countWidget, {
                        max: 16,
                        prefix: "line_",
                        type: "STRING",
                        firstIndex: 0,
                    });
                }
            };

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);

                try {
                    wireCountWidget(this, "count", () => applyOutputCount(this));
                } catch (e) {
                    console.error("Wudd MultiTextSplitter Error:", e);
                }
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (config) {
                if (onConfigure) onConfigure.apply(this, arguments);
                try { applyOutputCount(this); } catch (e) {}
            };
        }

        // ==========================================
        // WuddImageListImporter — 动态输入与输出
        // ==========================================
        if (nodeData.name === "WuddImageListImporter") {
            function applyImageCount(node) {
                const countWidget = node.widgets?.find(w => w.name === "image_count");
                if (!countWidget) return;

                syncOutputCount(node, countWidget, {
                    max: 50,
                    prefix: "image_",
                    type: "IMAGE",
                    firstIndex: 1,
                });

                const modeWidget = node.widgets?.find(w => w.name === "mode");
                const isFolder = modeWidget?.value === "folder";

                const count = clampInt(countWidget.value, 1, 50);
                let changed = false;
                for (let i = 0; i < (node.widgets?.length || 0); i++) {
                    const widget = node.widgets[i];
                    const idx = indexedSlotNumber(widget?.name, "image_");
                    if (idx == null) continue;

                    // folder 模式下隐藏全部 image_X 选择框；files 模式按 count 显隐
                    const visible = !isFolder && idx <= count;
                    changed = setWidgetVisible(widget, visible) || changed;

                    const maybeButton = node.widgets[i + 1];
                    const isUploadButton = maybeButton?.type === "button" ||
                        maybeButton?.__wuddOriginalType === "button" ||
                        maybeButton?.origType === "button";
                    if (isUploadButton) {
                        changed = setWidgetVisible(maybeButton, visible) || changed;
                    }
                }

                // folder_path 仅在 folder 模式可见
                const folderPathWidget = node.widgets?.find(w => w.name === "folder_path");
                if (folderPathWidget) {
                    changed = setWidgetVisible(folderPathWidget, isFolder) || changed;
                }

                if (changed) refreshNode(node);
            }

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);
                try {
                    wireCountWidget(this, "image_count", () => applyImageCount(this));
                    // mode 切换时也要刷新可见性
                    const modeWidget = this.widgets?.find(w => w.name === "mode");
                    if (modeWidget) {
                        const origCallback = modeWidget.callback;
                        modeWidget.callback = function () {
                            applyImageCount(this);
                            if (origCallback) return origCallback.apply(this, arguments);
                        }.bind(this);
                    }
                } catch (e) {
                    console.error("Wudd ImageListImporter Error:", e);
                }
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (config) {
                if (onConfigure) onConfigure.apply(this, arguments);
                try { applyImageCount(this); } catch (e) {}
            };
        }

        // ==========================================
        // WuddImageStitch — 按数量刷新输入端口
        // ==========================================
        if (nodeData.name === "WuddImageStitch") {
            const applyStitchInputCount = node => {
                const countWidget = node.widgets?.find(w => w.name === "input_count");
                if (countWidget) {
                    syncImageInputs(node, countWidget, {
                        max: 16,
                        prefix: "image_",
                        type: "IMAGE",
                    });
                }
            };

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);

                try {
                    wireCountWidget(this, "input_count", () => applyStitchInputCount(this));
                } catch (e) {
                    console.error("Wudd ImageStitch Error:", e);
                }
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (config) {
                if (onConfigure) onConfigure.apply(this, arguments);
                try { applyStitchInputCount(this); } catch (e) {}
            };
        }
    }
});
