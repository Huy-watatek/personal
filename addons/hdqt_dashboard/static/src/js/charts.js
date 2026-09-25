/* Inline-SVG chart primitives for the board dashboard.
 *
 * Hand-rolled rather than pulled from a chart library so the marks follow the
 * house spec exactly: bars capped at 24px with a 4px rounded data-end square at
 * the baseline, 2px lines with round joins, >=8px markers carrying a 2px surface
 * ring, hairline solid gridlines, and a legend whenever two series share a plot.
 * Colours are read from CSS custom properties, so light/dark swap in one place.
 */
(function () {
    "use strict";

    var NS = "http://www.w3.org/2000/svg";

    function svgEl(tag, attrs) {
        var node = document.createElementNS(NS, tag);
        for (var key in attrs) {
            if (attrs[key] !== null && attrs[key] !== undefined) {
                node.setAttribute(key, attrs[key]);
            }
        }
        return node;
    }

    function token(name) {
        var root = document.getElementById("hdqt-root") || document.documentElement;
        return getComputedStyle(root).getPropertyValue(name).trim() || "#888";
    }

    // ---------------------------------------------------------------- numbers

    function makeFormat(currency) {
        var decimals = (currency && currency.decimals) || 0;
        var symbol = (currency && currency.symbol) || "";
        var after = !currency || currency.position !== "before";

        function plain(value, digits) {
            return new Intl.NumberFormat("vi-VN", {
                minimumFractionDigits: digits === undefined ? 0 : digits,
                maximumFractionDigits: digits === undefined ? 0 : digits,
            }).format(value || 0);
        }
        return {
            integer: function (value) { return plain(Math.round(value || 0)); },
            currency: function (value) {
                var text = plain(value || 0, decimals);
                return after ? text + " " + symbol : symbol + " " + text;
            },
            // Axis ticks need to stay short; Vietnamese scale words beat "1.2M".
            compact: function (value) {
                var abs = Math.abs(value || 0);
                var sign = value < 0 ? "-" : "";
                if (abs >= 1e9) { return sign + plain(abs / 1e9, 1) + " tỷ"; }
                if (abs >= 1e6) { return sign + plain(abs / 1e6, 1) + " tr"; }
                if (abs >= 1e3) { return sign + plain(abs / 1e3, 0) + " k"; }
                return sign + plain(abs, 0);
            },
        };
    }

    /** Round an axis maximum up to a readable step. */
    function niceMax(value) {
        if (!value || value <= 0) { return 1; }
        var exponent = Math.pow(10, Math.floor(Math.log10(value)));
        var scaled = value / exponent;
        var step = scaled <= 1 ? 1 : scaled <= 2 ? 2 : scaled <= 2.5 ? 2.5 : scaled <= 5 ? 5 : 10;
        return step * exponent;
    }

    // ---------------------------------------------------------------- shapes

    /** Bar path with a rounded data-end and a square baseline end. */
    function barPath(x, y, width, height, radius, vertical) {
        var r = Math.max(0, Math.min(radius, vertical ? height : width, (vertical ? width : height) / 2));
        if (vertical) {
            var bottom = y + height;
            return "M" + x + "," + bottom +
                   "L" + x + "," + (y + r) +
                   "Q" + x + "," + y + " " + (x + r) + "," + y +
                   "L" + (x + width - r) + "," + y +
                   "Q" + (x + width) + "," + y + " " + (x + width) + "," + (y + r) +
                   "L" + (x + width) + "," + bottom + "Z";
        }
        var right = x + width;
        return "M" + x + "," + y +
               "L" + (right - r) + "," + y +
               "Q" + right + "," + y + " " + right + "," + (y + r) +
               "L" + right + "," + (y + height - r) +
               "Q" + right + "," + (y + height) + " " + (right - r) + "," + (y + height) +
               "L" + x + "," + (y + height) + "Z";
    }

    /** Shorten an SVG <text> until it fits ``limit`` px, keeping a full tooltip. */
    function fitText(node, limit) {
        var full = node.textContent;
        if (node.getComputedTextLength() <= limit) { return; }
        var low = 0;
        var high = full.length;
        while (low < high) {
            var mid = Math.ceil((low + high) / 2);
            node.textContent = full.slice(0, mid) + "…";
            if (node.getComputedTextLength() <= limit) { low = mid; } else { high = mid - 1; }
        }
        node.textContent = full.slice(0, low) + "…";
        // No <title> child here: textContent would then concatenate it back into
        // the label and the next measurement would read the doubled string.
        // The full name lives in the bar's hover tooltip and in the table view.
        node.setAttribute("aria-label", full);
    }

    // ---------------------------------------------------------------- tooltip

    function makeTooltip(container) {
        var node = document.createElement("div");
        node.className = "hdqt-tip";
        container.appendChild(node);
        return {
            show: function (html, x, y) {
                node.innerHTML = html;
                node.setAttribute("data-show", "1");
                var box = node.getBoundingClientRect();
                var width = container.clientWidth;
                var left = Math.min(Math.max(x - box.width / 2, 4), Math.max(width - box.width - 4, 4));
                node.style.left = left + "px";
                node.style.top = Math.max(y - box.height - 12, 0) + "px";
            },
            hide: function () { node.removeAttribute("data-show"); },
        };
    }

    function tipRow(color, label, value) {
        return '<div class="hdqt-tip-row">' +
               (color ? '<span class="hdqt-tip-swatch" style="background:' + color + '"></span>' : "") +
               "<span>" + escapeHtml(label) + '</span><span class="hdqt-tip-val">' + escapeHtml(value) + "</span></div>";
    }

    function escapeHtml(value) {
        return String(value === null || value === undefined ? "" : value)
            .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;");
    }

    // ---------------------------------------------------------------- chrome

    function reset(container) {
        Array.prototype.slice.call(container.childNodes).forEach(function (child) {
            container.removeChild(child);
        });
    }

    function empty(container, message) {
        reset(container);
        var node = document.createElement("p");
        node.className = "hdqt-empty";
        node.textContent = message || "Không có dữ liệu trong kỳ này.";
        container.appendChild(node);
    }

    function legend(container, items) {
        var box = document.createElement("div");
        box.className = "hdqt-legend";
        items.forEach(function (item) {
            var entry = document.createElement("span");
            entry.className = "hdqt-legend-item";
            entry.innerHTML = '<span class="hdqt-legend-swatch" style="background:' + item.color + '"></span>' +
                              escapeHtml(item.label);
            box.appendChild(entry);
        });
        container.appendChild(box);
    }

    /** Re-render on resize so text stays at its true pixel size. */
    function responsive(container, draw) {
        var pending = null;
        function run() {
            var width = container.clientWidth;
            if (width > 0) { draw(width); }
        }
        run();
        if (typeof ResizeObserver !== "undefined") {
            if (container._hdqtObserver) { container._hdqtObserver.disconnect(); }
            container._hdqtObserver = new ResizeObserver(function () {
                clearTimeout(pending);
                pending = setTimeout(run, 80);
            });
            container._hdqtObserver.observe(container);
        }
    }

    function gridAndAxis(svg, geometry, max, fmt) {
        var ticks = 4;
        for (var i = 0; i <= ticks; i++) {
            var value = (max / ticks) * i;
            var y = geometry.top + geometry.height - (value / max) * geometry.height;
            svg.appendChild(svgEl("line", {
                x1: geometry.left, x2: geometry.left + geometry.width, y1: y, y2: y,
                stroke: i === 0 ? token("--axis") : token("--grid"), "stroke-width": 1,
            }));
            var label = svgEl("text", {
                x: geometry.left - 8, y: y + 4, "text-anchor": "end",
                fill: token("--text-muted"), "font-size": 11,
                style: "font-variant-numeric:tabular-nums",
            });
            label.textContent = fmt(value);
            svg.appendChild(label);
        }
    }

    // ---------------------------------------------------------------- charts

    /** Multi-series line chart over a categorical x axis. One shared y scale. */
    function lineChart(container, options) {
        var series = (options.series || []).filter(function (item) {
            return (item.points || []).some(function (point) { return point; });
        });
        if (!series.length) { return empty(container, options.emptyText); }

        var colors = [token("--series-1"), token("--series-2")];
        reset(container);
        if (series.length >= 2) {
            legend(container, series.map(function (item, index) {
                return { label: item.label, color: colors[index % colors.length] };
            }));
        }
        var plot = document.createElement("div");
        plot.style.position = "relative";
        container.appendChild(plot);
        var tip = makeTooltip(plot);

        responsive(plot, function (width) {
            var old = plot.querySelector("svg");
            if (old) { plot.removeChild(old); }

            var labelRoom = series.length <= 4 ? 96 : 16;
            var geometry = { left: 68, top: 14, right: labelRoom, bottom: 26 };
            var height = 300;
            geometry.width = Math.max(width - geometry.left - geometry.right, 40);
            geometry.height = height - geometry.top - geometry.bottom;

            var max = niceMax(Math.max.apply(null, series.map(function (item) {
                return Math.max.apply(null, item.points);
            })) * 1.05);

            var svg = svgEl("svg", {
                viewBox: "0 0 " + width + " " + height, width: width, height: height,
                role: "img", "aria-label": options.ariaLabel || "",
            });
            gridAndAxis(svg, geometry, max, options.fmtAxis);

            var count = options.labels.length;
            function xAt(index) {
                return count === 1
                    ? geometry.left + geometry.width / 2
                    : geometry.left + (geometry.width / (count - 1)) * index;
            }
            function yAt(value) {
                return geometry.top + geometry.height - ((value || 0) / max) * geometry.height;
            }

            options.labels.forEach(function (text, index) {
                if (count > 8 && index % 2 === 1) { return; }
                var label = svgEl("text", {
                    x: xAt(index), y: geometry.top + geometry.height + 18, "text-anchor": "middle",
                    fill: token("--text-muted"), "font-size": 11,
                });
                label.textContent = text;
                svg.appendChild(label);
            });

            var crosshair = svgEl("line", {
                y1: geometry.top, y2: geometry.top + geometry.height,
                stroke: token("--axis"), "stroke-width": 1, opacity: 0,
            });
            svg.appendChild(crosshair);

            series.forEach(function (item, sIndex) {
                var color = colors[sIndex % colors.length];
                var d = item.points.map(function (value, index) {
                    return (index ? "L" : "M") + xAt(index) + "," + yAt(value);
                }).join(" ");
                svg.appendChild(svgEl("path", {
                    d: d, fill: "none", stroke: color, "stroke-width": 2,
                    "stroke-linejoin": "round", "stroke-linecap": "round",
                }));
                // End dot with a 2px surface ring, plus a direct label.
                var lastIndex = item.points.length - 1;
                svg.appendChild(svgEl("circle", {
                    cx: xAt(lastIndex), cy: yAt(item.points[lastIndex]), r: 4,
                    fill: color, stroke: token("--surface-1"), "stroke-width": 2,
                }));
                if (series.length <= 4 && labelRoom > 20) {
                    var direct = svgEl("text", {
                        x: xAt(lastIndex) + 10, y: yAt(item.points[lastIndex]) + 4,
                        fill: token("--text-secondary"), "font-size": 11,
                        style: "font-variant-numeric:tabular-nums",
                    });
                    direct.textContent = options.fmtAxis(item.points[lastIndex]);
                    svg.appendChild(direct);
                }
            });

            var markers = series.map(function (item, sIndex) {
                var dot = svgEl("circle", {
                    r: 4, fill: colors[sIndex % colors.length],
                    stroke: token("--surface-1"), "stroke-width": 2, opacity: 0,
                });
                svg.appendChild(dot);
                return dot;
            });

            svg.appendChild(svgEl("rect", {
                x: geometry.left, y: geometry.top,
                width: geometry.width, height: geometry.height,
                fill: "transparent", style: "cursor:crosshair",
            }));

            svg.addEventListener("mousemove", function (event) {
                var bounds = svg.getBoundingClientRect();
                var x = event.clientX - bounds.left;
                var step = count === 1 ? 1 : geometry.width / (count - 1);
                var index = Math.round((x - geometry.left) / step);
                if (index < 0 || index >= count) { return; }
                crosshair.setAttribute("x1", xAt(index));
                crosshair.setAttribute("x2", xAt(index));
                crosshair.setAttribute("opacity", 1);
                var rows = series.map(function (item, sIndex) {
                    markers[sIndex].setAttribute("cx", xAt(index));
                    markers[sIndex].setAttribute("cy", yAt(item.points[index]));
                    markers[sIndex].setAttribute("opacity", 1);
                    return tipRow(colors[sIndex % colors.length], item.label,
                                  options.fmtValue(item.points[index]));
                });
                tip.show('<div class="hdqt-tip-title">' +
                         escapeHtml((options.fullLabels || options.labels)[index]) + "</div>" + rows.join(""),
                         xAt(index), yAt(Math.max.apply(null, series.map(function (item) {
                             return item.points[index] || 0;
                         }))));
            });
            svg.addEventListener("mouseleave", function () {
                crosshair.setAttribute("opacity", 0);
                markers.forEach(function (dot) { dot.setAttribute("opacity", 0); });
                tip.hide();
            });

            plot.appendChild(svg);
        });
    }

    /** Horizontal bars — the form for ranked items with long labels. */
    function hBarChart(container, options) {
        var rows = (options.rows || []).filter(function (row) { return row.value; });
        if (!rows.length) { return empty(container, options.emptyText); }

        reset(container);
        var plot = document.createElement("div");
        plot.style.position = "relative";
        container.appendChild(plot);
        var tip = makeTooltip(plot);
        var color = token("--series-1");

        responsive(plot, function (width) {
            var old = plot.querySelector("svg");
            if (old) { plot.removeChild(old); }

            var labelsToFit = [];
            var barHeight = 18;
            var gap = 10;               // well past the 2px surface gap minimum
            var labelWidth = Math.min(Math.max(width * 0.34, 90), 210);
            var valueWidth = 96;
            var trackWidth = Math.max(width - labelWidth - valueWidth, 40);
            var height = rows.length * (barHeight + gap) + gap;
            var max = Math.max.apply(null, rows.map(function (row) { return Math.abs(row.value); })) || 1;

            var svg = svgEl("svg", {
                viewBox: "0 0 " + width + " " + height, width: width, height: height,
                role: "img", "aria-label": options.ariaLabel || "",
            });

            var labelGap = 10;
            var barStart = labelWidth + labelGap;

            rows.forEach(function (row, index) {
                var y = gap + index * (barHeight + gap);
                var barWidth = Math.max((Math.abs(row.value) / max) * trackWidth, 2);

                var label = svgEl("text", {
                    x: 0, y: y + barHeight - 4, fill: token("--text-secondary"), "font-size": 12,
                });
                label.textContent = row.label;
                svg.appendChild(label);
                labelsToFit.push(label);

                var bar = svgEl("path", {
                    d: barPath(barStart, y, barWidth, barHeight, 4, false),
                    fill: color, style: "cursor:pointer",
                });
                svg.appendChild(bar);

                var value = svgEl("text", {
                    x: barStart + barWidth + 8, y: y + barHeight - 4,
                    fill: token("--text-primary"), "font-size": 12,
                    style: "font-variant-numeric:tabular-nums",
                });
                value.textContent = options.fmtAxis(row.value);
                svg.appendChild(value);

                bar.addEventListener("mousemove", function (event) {
                    var bounds = svg.getBoundingClientRect();
                    tip.show('<div class="hdqt-tip-title">' + escapeHtml(row.label) + "</div>" +
                             tipRow(color, options.valueLabel || "Giá trị", options.fmtValue(row.value)),
                             event.clientX - bounds.left, y + barHeight);
                });
                bar.addEventListener("mouseleave", tip.hide);
            });

            plot.appendChild(svg);
            // Trim by measuring the rendered glyphs: a character estimate is wrong
            // for Vietnamese, where diacritics and proportional widths vary a lot.
            labelsToFit.forEach(function (node) {
                fitText(node, labelWidth);
            });
        });
    }

    /** Vertical bars over a small ordered set of categories. */
    function barChart(container, options) {
        var rows = options.rows || [];
        if (!rows.some(function (row) { return row.value; })) { return empty(container, options.emptyText); }

        reset(container);
        var plot = document.createElement("div");
        plot.style.position = "relative";
        container.appendChild(plot);
        var tip = makeTooltip(plot);

        var ramp = options.ordinal
            ? [token("--ord-1"), token("--ord-2"), token("--ord-3"), token("--ord-4")]
            : null;
        var flat = token("--series-1");

        responsive(plot, function (width) {
            var old = plot.querySelector("svg");
            if (old) { plot.removeChild(old); }

            var geometry = { left: 68, top: 22, right: 8, bottom: 30 };
            var height = 260;
            geometry.width = Math.max(width - geometry.left - geometry.right, 40);
            geometry.height = height - geometry.top - geometry.bottom;

            var max = niceMax(Math.max.apply(null, rows.map(function (row) {
                return Math.abs(row.value);
            })) * 1.15);

            var svg = svgEl("svg", {
                viewBox: "0 0 " + width + " " + height, width: width, height: height,
                role: "img", "aria-label": options.ariaLabel || "",
            });
            gridAndAxis(svg, geometry, max, options.fmtAxis);

            var band = geometry.width / rows.length;
            var barWidth = Math.min(band - 12, 24);   // cap the mark; leave the rest as air

            rows.forEach(function (row, index) {
                var color = ramp ? ramp[Math.min(index, ramp.length - 1)] : flat;
                var value = Math.abs(row.value);
                var barHeight = Math.max((value / max) * geometry.height, value ? 2 : 0);
                var x = geometry.left + band * index + (band - barWidth) / 2;
                var y = geometry.top + geometry.height - barHeight;

                if (barHeight) {
                    var bar = svgEl("path", {
                        d: barPath(x, y, barWidth, barHeight, 4, true),
                        fill: color, style: "cursor:pointer",
                    });
                    svg.appendChild(bar);
                    bar.addEventListener("mousemove", function (event) {
                        var bounds = svg.getBoundingClientRect();
                        tip.show('<div class="hdqt-tip-title">' + escapeHtml(row.label) + "</div>" +
                                 tipRow(color, options.valueLabel || "Giá trị", options.fmtValue(row.value)),
                                 event.clientX - bounds.left, y);
                    });
                    bar.addEventListener("mouseleave", tip.hide);
                }

                var direct = svgEl("text", {
                    x: x + barWidth / 2, y: y - 7, "text-anchor": "middle",
                    fill: token("--text-primary"), "font-size": 11,
                    style: "font-variant-numeric:tabular-nums",
                });
                direct.textContent = options.fmtAxis(row.value);
                svg.appendChild(direct);

                var label = svgEl("text", {
                    x: x + barWidth / 2, y: geometry.top + geometry.height + 18, "text-anchor": "middle",
                    fill: token("--text-muted"), "font-size": 11,
                });
                label.textContent = row.label;
                svg.appendChild(label);
            });

            plot.appendChild(svg);
        });
    }

    window.HdqtCharts = {
        lineChart: lineChart,
        hBarChart: hBarChart,
        barChart: barChart,
        makeFormat: makeFormat,
        escapeHtml: escapeHtml,
        empty: empty,
    };
})();
