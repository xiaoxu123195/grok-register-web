/**
 * Clipboard helper that also works outside a secure context.
 *
 * `navigator.clipboard` is only exposed on HTTPS or on localhost/127.0.0.1.
 * A server deployment reached over plain `http://<ip>:<port>` has no Clipboard
 * API at all, so calling it throws `TypeError` inside the click handler and the
 * button silently does nothing. Fall back to the legacy `execCommand('copy')`
 * path so remote HTTP deployments keep working.
 */

function legacyCopy(value) {
    const textarea = document.createElement('textarea');
    textarea.value = value;
    textarea.setAttribute('readonly', '');
    // Keep it off-screen but still selectable (display:none would break copy).
    textarea.style.position = 'fixed';
    textarea.style.top = '-1000px';
    textarea.style.left = '-1000px';
    textarea.style.opacity = '0';
    document.body.appendChild(textarea);

    const selection = document.getSelection();
    const previousRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null;

    try {
        textarea.focus({ preventScroll: true });
        textarea.select();
        textarea.setSelectionRange(0, value.length);
        return document.execCommand('copy');
    } catch {
        return false;
    } finally {
        textarea.remove();
        if (selection && previousRange) {
            selection.removeAllRanges();
            selection.addRange(previousRange);
        }
    }
}

/**
 * Copy text to the clipboard. Returns true on success.
 * Never throws — callers decide how to report failure.
 */
export async function copyText(text) {
    const value = String(text ?? '');
    if (!value) return false;

    if (window.isSecureContext && navigator.clipboard?.writeText) {
        try {
            await navigator.clipboard.writeText(value);
            return true;
        } catch {
            // Permission denied / document not focused — try the legacy path.
        }
    }
    return legacyCopy(value);
}

/**
 * Copy and report the outcome through a toast callback.
 * `showToast` is injected so this module stays free of UI imports.
 */
export async function copyTextWithToast(text, showToast, successMessage) {
    const ok = await copyText(text);
    if (ok) {
        showToast(successMessage, 'success');
    } else {
        showToast('复制失败：浏览器拒绝了剪切板访问，请手动选中文本复制', 'error');
    }
    return ok;
}
