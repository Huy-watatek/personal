/* Wiring for /hdqt/dashboard: filters -> fetch -> render. */
(function () {
    "use strict";

    var charts = window.HdqtCharts;
    var state = { from: null, to: null, companies: [], fmt: charts.makeFormat(null) };

    function $(id) { return document.getElementById(id); }

    function iso(date) {
        return date.getFullYear() + "-" +
               String(date.getMonth() + 1).padStart(2, "0") + "-" +
               String(date.getDate()).padStart(2, "0");
    }

    function presetRange(key) {
        var today = new Date();
        var start;
        if (key === "qtd") {
            start = new Date(today.getFullYear(), Math.floor(today.getMonth() / 3) * 3, 1);
        } else if (key === "ytd") {
            start = new Date(today.getFullYear(), 0, 1);
        } else if (key === "d30") {
            start = new Date(today.getTime() - 29 * 86400000);
        } else {
            start = new Date(today.getFullYear(), today.getMonth(), 1);
        }
        return { from: iso(start), to: iso(today) };
    }

    // ------------------------------------------------------------------ theme

    function readTheme() {
        try { return localStorage.getItem("hdqt-theme"); } catch (err) { return null; }
    }
    function writeTheme(value) {
        try { localStorage.setItem("hdqt-theme", value); } catch (err) { /* private mode */ }
    }
    function setupTheme() {
        var stored = readTheme();
        if (stored) { document.documentElement.setAttribute("data-theme", stored); }
        $("hdqt-theme").addEventListener("click", function () {
            var current = document.documentElement.getAttribute("data-theme");
            if (!current) {
                var prefersDark = window.matchMedia &&
                    window.matchMedia("(prefers-color-scheme: dark)").matches;
                current = prefersDark ? "dark" : "light";
            }
            var next = current === "dark" ? "light" : "dark";
            document.documentElement.setAttribute("data-theme", next);
            writeTheme(next);
            render(state.data);   // colours are read at draw time
        });
    }

    // -------------------------------------------------------------------- KPI

    function renderKpis(kpis) {
        var host = $("hdqt-kpis");
        host.innerHTML = "";
        kpis.forEach(function (kpi) {
            // A full VND figure (3.184.000.000 ₫) wraps inside a tile and breaks the
            // row; lead with the compact form and keep the exact number on hover.
            var exact = kpi.format === "currency"
                ? state.fmt.currency(kpi.value)
                : state.fmt.integer(kpi.value);
            var value = kpi.format === "currency" ? state.fmt.compact(kpi.value) : exact;

            var deltaHtml = "";
            if (kpi.delta !== null && kpi.delta !== undefined) {
                var rising = kpi.delta > 0;
                var flat = Math.abs(kpi.delta) < 0.05;
                var good = flat ? "is-flat"
                    : (rising === (kpi.delta_good === "up") ? "is-good" : "is-bad");
                // An arrow plus a sign, so direction never rests on colour alone.
                var arrow = flat ? "→" : (rising ? "↑" : "↓");
                deltaHtml = '<span class="hdqt-kpi-delta ' + good + '">' + arrow + " " +
                            Math.abs(kpi.delta).toFixed(1).replace(".", ",") + "%</span>";
            }

            var card = document.createElement("div");
            card.className = "hdqt-kpi";
            card.innerHTML =
                '<p class="hdqt-kpi-label">' + charts.escapeHtml(kpi.label) + "</p>" +
                '<p class="hdqt-kpi-value" title="' + charts.escapeHtml(exact) + '">' +
                    charts.escapeHtml(value) + "</p>" +
                '<div class="hdqt-kpi-foot">' + deltaHtml +
                '<span class="hdqt-kpi-hint">' + charts.escapeHtml(kpi.hint || "") + "</span></div>";
            host.appendChild(card);
        });
    }

    // ------------------------------------------------------------------ table

    function renderTable(id, headers, rows) {
        var host = $(id);
        if (!host) { return; }
        if (!rows.length) { host.innerHTML = "<p>Không có dữ liệu.</p>"; return; }
        var head = headers.map(function (header, index) {
            return '<th class="' + (index ? "num" : "") + '">' + charts.escapeHtml(header) + "</th>";
        }).join("");
        var body = rows.map(function (row) {
            return "<tr>" + row.map(function (cell, index) {
                return '<td class="' + (index ? "num" : "") + '">' + charts.escapeHtml(cell) + "</td>";
            }).join("") + "</tr>";
        }).join("");
        host.innerHTML = "<table><thead><tr>" + head + "</tr></thead><tbody>" + body + "</tbody></table>";
    }

    // ----------------------------------------------------------------- render

    function toggleCard(id, visible) {
        var card = $(id);
        if (card) { card.hidden = !visible; }
    }

    function render(data) {
        if (!data) { return; }
        state.data = data;
        state.fmt = charts.makeFormat(data.currency);
        var money = { fmtAxis: state.fmt.compact, fmtValue: state.fmt.currency };
        var counts = { fmtAxis: state.fmt.integer, fmtValue: state.fmt.integer };

        $("hdqt-period").textContent = "Kỳ " + data.period.from + " → " + data.period.to +
            " · so với " + data.period.previous_from + " → " + data.period.previous_to;
        $("hdqt-generated").textContent = "Cập nhật " + data.generated_at;

        renderKpis(data.kpis || []);

        // Trend ---------------------------------------------------------
        var trend = data.revenue_trend || { labels: [], series: [] };
        toggleCard("card-trend", (trend.series || []).length > 0);
        charts.lineChart($("chart-trend"), {
            labels: trend.labels, fullLabels: trend.full_labels, series: trend.series,
            fmtAxis: money.fmtAxis, fmtValue: money.fmtValue,
            ariaLabel: "Doanh số chốt và doanh thu xuất hoá đơn theo tháng",
        });
        renderTable("table-trend",
            ["Tháng"].concat((trend.series || []).map(function (s) { return s.label; })),
            (trend.labels || []).map(function (label, index) {
                return [trend.full_labels[index]].concat((trend.series || []).map(function (s) {
                    return state.fmt.currency(s.points[index]);
                }));
            }));

        // Ageing --------------------------------------------------------
        var aging = data.ar_aging || [];
        toggleCard("card-aging", aging.length > 0);
        charts.barChart($("chart-aging"), {
            rows: aging, ordinal: true, valueLabel: "Số dư",
            fmtAxis: money.fmtAxis, fmtValue: money.fmtValue,
            ariaLabel: "Tuổi nợ phải thu theo nhóm ngày quá hạn",
        });
        renderTable("table-aging", ["Nhóm", "Số dư"], aging.map(function (row) {
            return [row.label, state.fmt.currency(row.value)];
        }));

        // Customers -----------------------------------------------------
        var customers = data.top_customers || [];
        toggleCard("card-customers", customers.length > 0);
        charts.hBarChart($("chart-customers"), {
            rows: customers, valueLabel: "Doanh số",
            fmtAxis: money.fmtAxis, fmtValue: money.fmtValue,
            ariaLabel: "Khách hàng theo doanh số",
        });
        renderTable("table-customers", ["Khách hàng", "Doanh số"], customers.map(function (row) {
            return [row.label, state.fmt.currency(row.value)];
        }));

        // Operations ----------------------------------------------------
        var operations = data.operations || {};
        [["mrp", "Lệnh sản xuất"], ["picking", "Phiếu kho"]].forEach(function (pair) {
            var key = pair[0];
            var rows = operations[key] || [];
            toggleCard("card-" + key, rows.length > 0);
            charts.barChart($("chart-" + key), {
                rows: rows, valueLabel: pair[1],
                fmtAxis: counts.fmtAxis, fmtValue: counts.fmtValue,
                ariaLabel: pair[1] + " theo trạng thái",
            });
            renderTable("table-" + key, ["Trạng thái", "Số lượng"], rows.map(function (row) {
                return [row.label, state.fmt.integer(row.value)];
            }));
        });
    }

    // ------------------------------------------------------------------ fetch

    function showError(message) {
        var node = $("hdqt-error");
        node.textContent = message;
        node.hidden = !message;
    }

    function load() {
        showError("");
        var params = new URLSearchParams();
        if (state.from) { params.set("date_from", state.from); }
        if (state.to) { params.set("date_to", state.to); }
        if (state.companies.length) { params.set("company_ids", state.companies.join(",")); }

        fetch("/hdqt/dashboard/data?" + params.toString(), {
            credentials: "same-origin",
            headers: { Accept: "application/json" },
        }).then(function (response) {
            if (!response.ok) { throw new Error("HTTP " + response.status); }
            return response.json();
        }).then(function (data) {
            if (data.error) { throw new Error(data.error); }
            syncCompanies(data.companies || []);
            render(data);
        }).catch(function (error) {
            showError("Không tải được số liệu: " + error.message +
                      ". Kiểm tra quyền truy cập hoặc log máy chủ.");
        });
    }

    function syncCompanies(companies) {
        var wrap = $("hdqt-company-wrap");
        var select = $("hdqt-company");
        if (companies.length < 2) { wrap.hidden = true; return; }
        wrap.hidden = false;
        if (select.options.length === companies.length) { return; }
        select.innerHTML = "";
        select.size = Math.min(companies.length, 4);
        companies.forEach(function (company) {
            var option = document.createElement("option");
            option.value = company.id;
            option.textContent = company.name;
            option.selected = company.selected;
            select.appendChild(option);
        });
    }

    // ------------------------------------------------------------------- init

    function markChip(active) {
        Array.prototype.forEach.call(document.querySelectorAll(".hdqt-chip"), function (chip) {
            chip.setAttribute("aria-pressed", String(chip.dataset.range === active));
        });
    }

    function applyPreset(key) {
        var range = presetRange(key);
        state.from = range.from;
        state.to = range.to;
        $("hdqt-from").value = range.from;
        $("hdqt-to").value = range.to;
        markChip(key);
        load();
    }

    function init() {
        setupTheme();

        Array.prototype.forEach.call(document.querySelectorAll(".hdqt-chip"), function (chip) {
            chip.addEventListener("click", function () { applyPreset(chip.dataset.range); });
        });

        $("hdqt-apply").addEventListener("click", function () {
            state.from = $("hdqt-from").value || null;
            state.to = $("hdqt-to").value || null;
            state.companies = Array.prototype.filter.call($("hdqt-company").options, function (option) {
                return option.selected;
            }).map(function (option) { return option.value; });
            markChip(null);
            load();
        });

        applyPreset("mtd");
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
