"""Interactive pieces of the Net Worth page that need a click to reach
Python, built on anywidget and wrapped with mo.ui.anywidget() in the
notebook. The rest of the finance dashboards is static HTML from
finance_ui.py."""

import anywidget
import traitlets

# A 100% bar (% labels on slices wide
# enough to hold them) with a clickable chip row above it. The widget renders in its
# own shadow root, so the notebook's STYLE doesn't reach it: its CSS is here.
_ESM = r"""
const money = (v) =>
  (v < 0 ? "-$" : "$") + Math.round(Math.abs(v)).toLocaleString("en-US");

function render({ model, el }) {
  const draw = () => {
    el.replaceChildren();
    const names = model.get("names");
    const values = model.get("values");
    const colors = model.get("colors");
    const chips = model.get("chips");
    const selected = model.get("selected");
    const total = values.reduce((a, b) => a + b, 0);
    const pick = (name) => {
      const next = name === selected && model.get("allow_none") ? "" : name;
      model.set("selected", next);
      model.save_changes();
    };

    const row = document.createElement("div");
    row.className = "chips";
    const chip = (name, text, color) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "chip" + (name === selected ? " on" : "");
      if (color) {
        const dot = document.createElement("span");
        dot.className = "dot";
        dot.style.background = color;
        b.append(dot);
      }
      b.append(text);
      b.onclick = () => pick(name);
      row.append(b);
    };
    names.forEach((n, i) =>
      chip(n, `${n} ${total ? Math.round((values[i] / total) * 100) : 0}%`, colors[i])
    );
    chips.forEach(([n, text]) => chip(n, text, null));
    el.append(row);

    if (!names.length || !total) return;
    // Flex divs rather than an SVG, so the bar keeps its height on a phone
    const bar = document.createElement("div");
    bar.className = "bar";
    bar.style.height = `${model.get("height")}px`;
    names.forEach((n, i) => {
      const share = values[i] / total;
      const seg = document.createElement("div");
      seg.className = "seg" + (selected && n !== selected ? " dim" : "");
      seg.style.flex = `${share} 0 0`;
      seg.style.background = colors[i];
      seg.title = `${n}: ${money(values[i])} (${(share * 100).toFixed(1)}%)`;
      const label = document.createElement("span");
      label.textContent = `${Math.round(share * 100)}%`;
      seg.append(label);
      seg.onclick = () => pick(n);
      bar.append(seg);
    });
    el.append(bar);
    // Only label slices wide enough to hold it
    requestAnimationFrame(() =>
      bar.querySelectorAll(".seg").forEach((seg) => {
        seg.firstChild.style.visibility =
          seg.clientWidth >= seg.firstChild.offsetWidth + 8 ? "visible" : "hidden";
      })
    );
  };
  draw();
  model.on("change", draw);
}
export default { render };
"""

_CSS = """
.chips { display: flex; flex-wrap: wrap; gap: 0.4rem; margin: 0 0 0.7rem; }
.chip {
  font-family: 'IBM Plex Mono', monospace; font-size: 0.75rem;
  letter-spacing: 0.04em; color: #8a93a6; background: #0f1218;
  border: 1px solid #1e2330; border-radius: 999px; padding: 0.3rem 0.75rem;
  cursor: pointer; display: inline-flex; align-items: center; gap: 0.45rem;
}
.chip:hover { color: #e8edf5; border-color: #3a4256; }
.chip.on { color: #E8890C; border-color: #E8890C; }
.dot { width: 0.6rem; height: 0.6rem; border-radius: 2px; display: inline-block; }
.bar { display: flex; width: 100%; gap: 1px; }
.seg {
  cursor: pointer; transition: opacity 0.15s; min-width: 2px; overflow: hidden;
  display: flex; align-items: center; justify-content: center;
}
.seg.dim { opacity: 0.35; }
.seg:hover { opacity: 1; }
.seg span {
  color: #0a0c0f; font: 600 0.8rem 'IBM Plex Mono', monospace; pointer-events: none;
  white-space: nowrap;
}
"""


class ShareBar(anywidget.AnyWidget):
    """A 100% bar of names and values whose segments, and the chip row above
    them, set `selected` when clicked. `chips` adds chip-only entries
    ([name, label] pairs, e.g. Liabilities, which has no share of the
    assets). With `allow_none`, clicking the selected entry clears it."""

    _esm = _ESM
    _css = _CSS
    names = traitlets.List(traitlets.Unicode()).tag(sync=True)
    values = traitlets.List(traitlets.Float()).tag(sync=True)
    colors = traitlets.List(traitlets.Unicode()).tag(sync=True)
    chips = traitlets.List(traitlets.List()).tag(sync=True)
    selected = traitlets.Unicode("").tag(sync=True)
    allow_none = traitlets.Bool(False).tag(sync=True)
    height = traitlets.Int(34).tag(sync=True)
