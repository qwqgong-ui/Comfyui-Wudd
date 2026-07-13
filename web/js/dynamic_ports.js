import { app } from "../../../scripts/app.js";

function clampInt(value, min, max) {
    const n = Number.parseInt(value, 10);
    if (!Number.isFinite(n)) return min;
    return Math.max(min, Math.min(n, max));
}

function indexedSlotNumber(name, prefix) {
    const value = String(name || "");
    if (!value.startsWith(prefix)) return null;
    const suffix = value.slice(prefix.length);
    if (!/^\d+$/.test(suffix)) return null;
    const n = Number.parseInt(suffix, 10);
    return Number.isFinite(n) ? n : null;
}

function dynamicChildIndex(name, parentName, prefix) {
    return indexedSlotNumber(name, `${parentName}.${prefix}`) ??
        indexedSlotNumber(name, prefix);
}

function findDynamicChildWidget(node, parentName, childName) {
    return node.widgets?.find(w => w.name === `${parentName}.${childName}`) ||
        node.widgets?.find(w => w.name === childName) ||
        null;
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
    const countWidget = Array.isArray(widgetName)
        ? node.widgets?.find(w => widgetName.includes(w.name))
        : node.widgets?.find(w => w.name === widgetName);
    if (!countWidget) return null;

    countWidget.__wuddDynamicPortsApply = apply;
    if (countWidget.__wuddDynamicPortsWired) return countWidget;

    const origCallback = countWidget.callback;
    countWidget.callback = function () {
        countWidget.__wuddDynamicPortsApply?.();
        return origCallback?.apply(this, arguments);
    };
    countWidget.__wuddDynamicPortsWired = true;

    setTimeout(apply, 50);
    return countWidget;
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

app.registerExtension({
    name: "WuddV3.DynamicPorts",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name === "WuddV3MultiTextSplitter") {
            const applyOutputCount = node => {
                const countWidget = node.widgets?.find(w => w.name === "count");
                if (!countWidget) return;
                syncOutputCount(node, countWidget, {
                    max: 16,
                    prefix: "line_",
                    type: "STRING",
                    firstIndex: 0,
                });
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

        if (nodeData.name === "WuddV3ImageListImporter") {
            function scheduleImageCount(node) {
                const apply = () => {
                    try { applyImageCount(node); } catch (e) {
                        console.error("Wudd ImageListImporter Error:", e);
                    }
                };

                // DynamicCombo replaces all branch widgets whenever `mode`
                // changes. Run once after that synchronous rebuild and once
                // after the frontend has restored configured widget values.
                Promise.resolve().then(apply);
                setTimeout(apply, 50);
            }

            function wireImageWidgets(node) {
                const countWidget = findDynamicChildWidget(node, "mode", "image_count");
                if (countWidget) {
                    wireCountWidget(node, ["mode.image_count", "image_count"], () => applyImageCount(node));
                }

                const modeWidget = node.widgets?.find(w => w.name === "mode");
                if (modeWidget && !modeWidget.__wuddImageListModeWired) {
                    const origCallback = modeWidget.callback;
                    modeWidget.callback = function () {
                        const result = origCallback?.apply(this, arguments);
                        scheduleImageCount(node);
                        return result;
                    };
                    modeWidget.__wuddImageListModeWired = true;
                }
                return countWidget;
            }

            function applyImageCount(node) {
                const countWidget = wireImageWidgets(node);
                if (!countWidget) return;

                syncOutputCount(node, countWidget, {
                    max: 50,
                    prefix: "image_",
                    type: "IMAGE",
                    firstIndex: 1,
                });

                const count = clampInt(countWidget.value, 1, 50);
                let changed = false;

                for (let i = 0; i < (node.widgets?.length || 0); i++) {
                    const widget = node.widgets[i];
                    const idx = dynamicChildIndex(widget?.name, "mode", "image_");
                    if (idx == null) continue;

                    const visible = idx <= count;
                    changed = setWidgetVisible(widget, visible) || changed;

                    const maybeButton = node.widgets[i + 1];
                    const isUploadButton = maybeButton?.type === "button" ||
                        maybeButton?.__wuddOriginalType === "button" ||
                        maybeButton?.origType === "button";
                    if (isUploadButton) {
                        changed = setWidgetVisible(maybeButton, visible) || changed;
                    }
                }

                if (changed) refreshNode(node);
            }

            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = function () {
                if (onNodeCreated) onNodeCreated.apply(this, arguments);
                try {
                    wireImageWidgets(this);
                    scheduleImageCount(this);
                } catch (e) {
                    console.error("Wudd ImageListImporter Error:", e);
                }
            };

            const onConfigure = nodeType.prototype.onConfigure;
            nodeType.prototype.onConfigure = function (config) {
                if (onConfigure) onConfigure.apply(this, arguments);
                try { scheduleImageCount(this); } catch (e) {}
            };
        }
    }
});
