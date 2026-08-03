import { emaSeries } from "./indicators.js";
const svgElement = (tag, attributes) => {
    const element = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    return element;
};
const pathFrom = (values, x, y) => values
    .map((value, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(2)},${y(value).toFixed(2)}`)
    .join(" ");
export function renderPriceChart(container, candles, forecast) {
    container.replaceChildren();
    const visible = candles.slice(-(forecast.horizonMinutes === 60 ? 240 : 120));
    if (visible.length < 2)
        return;
    const closes = visible.map((candle) => candle.close);
    const ema9 = emaSeries(closes, 9);
    const ema21 = emaSeries(closes, 21);
    const points = visible.map((candle, index) => ({
        time: candle.time,
        close: candle.close,
        ema9: ema9[index] ?? candle.close,
        ema21: ema21[index] ?? candle.close,
    }));
    const width = 1000;
    const height = 360;
    const padding = { left: 64, right: 52, top: 24, bottom: 38 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const allPrices = [
        ...points.flatMap((point) => [point.close, point.ema9, point.ema21]),
        forecast.expectedLow,
        forecast.expectedHigh,
        forecast.predictedPrice,
    ];
    const rawMin = Math.min(...allPrices);
    const rawMax = Math.max(...allPrices);
    const margin = Math.max((rawMax - rawMin) * 0.12, forecast.currentPrice * 0.0005);
    const minPrice = rawMin - margin;
    const maxPrice = rawMax + margin;
    const totalSlots = points.length + forecast.horizonMinutes;
    const x = (index) => padding.left + (index / Math.max(1, totalSlots - 1)) * plotWidth;
    const y = (price) => padding.top + ((maxPrice - price) / Math.max(0.0001, maxPrice - minPrice)) * plotHeight;
    const wrapper = document.createElement("div");
    wrapper.className = "chart-wrap";
    const svg = svgElement("svg", {
        viewBox: `0 0 ${width} ${height}`,
        role: "img",
        "aria-label": `BTC price, EMA overlays, and ${forecast.horizonMinutes}-minute projection`,
    });
    for (let grid = 0; grid <= 4; grid += 1) {
        const gridY = padding.top + (grid / 4) * plotHeight;
        svg.append(svgElement("line", {
            x1: String(padding.left),
            y1: String(gridY),
            x2: String(width - padding.right),
            y2: String(gridY),
            class: "chart-grid",
        }));
        const labelValue = maxPrice - (grid / 4) * (maxPrice - minPrice);
        const label = svgElement("text", {
            x: String(padding.left - 10),
            y: String(gridY + 4),
            "text-anchor": "end",
            class: "chart-axis-label",
        });
        label.textContent = `$${labelValue.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
        svg.append(label);
    }
    const lastIndex = points.length - 1;
    const projectionX = x(totalSlots - 1);
    const rangeTop = y(forecast.expectedHigh);
    const rangeBottom = y(forecast.expectedLow);
    svg.append(svgElement("rect", {
        x: String(x(lastIndex)),
        y: String(rangeTop),
        width: String(projectionX - x(lastIndex)),
        height: String(Math.max(2, rangeBottom - rangeTop)),
        class: "projection-range",
        rx: "8",
    }));
    svg.append(svgElement("line", {
        x1: String(x(lastIndex)),
        y1: String(y(forecast.currentPrice)),
        x2: String(projectionX),
        y2: String(y(forecast.predictedPrice)),
        class: "projection-line",
    }));
    svg.append(svgElement("line", {
        x1: String(x(lastIndex)),
        y1: String(padding.top),
        x2: String(x(lastIndex)),
        y2: String(height - padding.bottom),
        class: "now-line",
    }));
    svg.append(svgElement("path", {
        d: pathFrom(points.map((point) => point.ema21), x, y),
        class: "ema21-line",
        fill: "none",
    }), svgElement("path", {
        d: pathFrom(points.map((point) => point.ema9), x, y),
        class: "ema9-line",
        fill: "none",
    }), svgElement("path", {
        d: pathFrom(points.map((point) => point.close), x, y),
        class: "price-line",
        fill: "none",
    }));
    const projectedPoint = svgElement("circle", {
        cx: String(projectionX),
        cy: String(y(forecast.predictedPrice)),
        r: "5",
        class: "projection-dot",
    });
    svg.append(projectedPoint);
    const tooltip = document.createElement("div");
    tooltip.className = "chart-tooltip hidden";
    const overlay = svgElement("rect", {
        x: String(padding.left),
        y: String(padding.top),
        width: String(plotWidth),
        height: String(plotHeight),
        fill: "transparent",
        class: "chart-overlay",
    });
    overlay.addEventListener("pointermove", (event) => {
        const rect = svg.getBoundingClientRect();
        const pointerX = ((event.clientX - rect.left) / rect.width) * width;
        const index = Math.round(((pointerX - padding.left) / plotWidth) * (totalSlots - 1));
        if (index >= points.length) {
            tooltip.innerHTML = `<strong>+${forecast.horizonMinutes}m projection</strong><span>$${forecast.predictedPrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span><span>Range $${forecast.expectedLow.toLocaleString(undefined, { maximumFractionDigits: 0 })}–$${forecast.expectedHigh.toLocaleString(undefined, { maximumFractionDigits: 0 })}</span>`;
        }
        else {
            const point = points[Math.max(0, Math.min(points.length - 1, index))];
            if (!point)
                return;
            tooltip.innerHTML = `<strong>${new Date(point.time).toLocaleTimeString("en-US", { timeZone: "America/Los_Angeles", hour: "numeric", minute: "2-digit", timeZoneName: "short" })}</strong><span>Price $${point.close.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span><span>EMA9 $${point.ema9.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span><span>EMA21 $${point.ema21.toLocaleString(undefined, { maximumFractionDigits: 2 })}</span>`;
        }
        tooltip.classList.remove("hidden");
        const localX = event.clientX - rect.left;
        const localY = event.clientY - rect.top;
        tooltip.style.left = `${Math.min(rect.width - 190, Math.max(8, localX + 12))}px`;
        tooltip.style.top = `${Math.max(8, localY - 78)}px`;
    });
    overlay.addEventListener("pointerleave", () => tooltip.classList.add("hidden"));
    svg.append(overlay);
    wrapper.append(svg, tooltip);
    container.append(wrapper);
}
