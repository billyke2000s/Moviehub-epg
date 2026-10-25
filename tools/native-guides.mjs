// Reuse MovieHub's audited interpreter to read public catalogue programmes on GitHub, never on the TV.
// No stream resolution, playback, media URLs, cookies or bearer tokens are published.
import { readFileSync, writeFileSync, mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { gzipSync } from "node:zlib";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import { join } from "node:path";

const PROVIDERS = ["stirr", "tcl", "xumo", "lg", "whale", "vizio", "roku", "tubi", "localnow", "freelivesports"];
const HOSTS = {
    stirr: ["stirr.com"], tcl: ["gateway-prod.ideonow.com"], xumo: ["valencia-app-mds.xumo.com"],
    lg: ["api.lgchannels.com"], whale: ["rlaxx.zeasn.tv"], vizio: ["watchfreeplus-epg-prod.smartcasttv.com"],
    roku: ["therokuchannel.roku.com", "content.sr.roku.com"],
    tubi: ["tubi.io", "adrise.io", "tubi.video", "tubitv.com"],
    localnow: ["localnow.com", "localnowapi.com", "amdvids.com"], freelivesports: ["epg.unreel.me"],
};
const escape = value => String(value || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
const stamp = value => new Date(value).toISOString().replace(/[-:]/g, "").replace(/T/, "").slice(0, 14) + " +0000";

export function nativeXml(provider, rows, now = Date.now()) {
    const prefix = provider === "freelivesports" ? "enginefls" : "engine" + provider;
    const channels = [], programmes = [];
    for (const row of rows) {
        if (typeof row.channelId !== "string" || !row.channelId || row.channelId.length > 400) continue;
        const id = prefix + ":" + row.channelId;
        const usable = [];
        for (const p of row.programs || []) {
            const start = Date.parse(p.start), stop = Date.parse(p.end);
            if (!Number.isFinite(start) || !Number.isFinite(stop) || stop <= start || !p.title) continue;
            if (stop <= now - 86400000 || start >= now + 7 * 86400000) continue;
            usable.push(`<programme channel="${escape(id)}" start="${stamp(start)}" stop="${stamp(stop)}"><title>${escape(p.title)}</title><desc>${escape((p.desc || "").slice(0, 400))}</desc><category>${escape(p.genre || "")}</category></programme>`);
        }
        if (!usable.length) continue;
        channels.push(`<channel id="${escape(id)}"><display-name>${escape(row.name || row.channelId)}</display-name></channel>`);
        programmes.push(...usable);
    }
    if (!programmes.length) throw new Error("No usable inline programmes");
    return { xml: `<?xml version="1.0" encoding="UTF-8"?><tv>${channels.join("")}${programmes.join("")}</tv>`, channels: channels.length, programmes: programmes.length };
}

async function main() {
    const source = process.env.MOVIEHUB_SOURCE || "moviehub-source";
    const pkg = JSON.parse(readFileSync(source + "/android-tv-launcher/app/src/main/assets/providers/builtin.json"));
    const root = ".cache/native";
    mkdirSync(root, { recursive: true });
    const work = mkdtempSync(join(tmpdir(), "moviehub-epg-provider-"));
    const reports = [];
    for (const id of PROVIDERS) {
        // Snapshots are fresh only after this run succeeds. The accepted per-source cache
        // is a separate file, with original timestamps retained by the Python merger.
        rmSync(`${root}/${id}.xml.gz`, { force: true });
        const deadline = Date.now() + 90000;
        const dir = `${work}/${id}`;
        mkdirSync(dir, { recursive: true });
        function step(operation, input) {
            writeFileSync(dir + "/module.js", pkg.modules[id]);
            writeFileSync(dir + "/input.json", typeof input === "string" ? input : JSON.stringify(input));
            const p = spawnSync("java", ["-Xmx256m", "-cp", process.env.RHINO_JAR + ":build/provider-tests", "local.tv.home.ProviderProbeCli", dir + "/module.js", operation, dir + "/input.json"], { encoding: "utf8", maxBuffer: 48 * 1024 * 1024, timeout: 45000 });
            if (p.status !== 0) throw new Error("Interpreter did not complete");
            return JSON.parse(p.stdout);
        }
        let requests = 0, bytes = 0;
        async function exchange(request) {
            if (Date.now() > deadline) throw new Error("Catalogue time limit");
            if (request.url.startsWith("https://provider-timer.invalid/")) {
                const ms = Number(request.url.slice("https://provider-timer.invalid/".length));
                if (!Number.isFinite(ms) || ms < 0 || ms > 3000) throw new Error("Catalogue timer limit");
                await new Promise(resolve => setTimeout(resolve, ms));
                return { status: 200, url: request.url, headers: {}, text: "" };
            }
            let address = request.url, method = request.method || "GET", body = request.body || "";
            const first = new URL(address).host;
            for (let redirects = 0; redirects < 5; redirects++) {
                const u = new URL(address);
                if (u.protocol !== "https:" || u.username || u.password || u.port || !HOSTS[id].some(h => u.hostname === h || u.hostname.endsWith("." + h))) throw new Error("Catalogue target outside capability");
                if (!['GET', 'POST'].includes(method) || ++requests > 64) throw new Error("Catalogue request limit");
                const headers = Object.fromEntries(Object.entries(request.headers || {}).filter(([k]) => u.host === first || ["user-agent", "accept", "accept-language", "origin", "referer"].includes(k.toLowerCase())));
                const r = await fetch(address, { method, headers, body: method === "POST" ? body : undefined, redirect: "manual", signal: AbortSignal.timeout(16000) });
                if (r.status >= 300 && r.status < 400) {
                    address = new URL(r.headers.get("location"), address).href;
                    if (r.status === 303 || ((r.status === 301 || r.status === 302) && method === "POST")) { method = "GET"; body = ""; }
                    continue;
                }
                // An upstream denial ends this provider; no alternate identities/regions are tried.
                if ([401, 403, 429].includes(r.status)) throw new Error("Provider refused public catalogue: HTTP " + r.status);
                const chunks = [];
                let size = 0;
                for await (const chunk of r.body) {
                    size += chunk.length;
                    if (size > 6 * 1024 * 1024) throw new Error("Catalogue response limit");
                    chunks.push(chunk);
                }
                const buffer = Buffer.concat(chunks);
                bytes += buffer.length;
                if (buffer.length > 6 * 1024 * 1024 || bytes > 15 * 1024 * 1024) throw new Error("Catalogue response limit");
                return { status: r.status, url: address, headers: Object.fromEntries(r.headers.entries()), text: buffer.toString("utf8"), bytes: u.pathname.endsWith(".gz") ? buffer.toString("base64") : "", cookies: [] };
            }
            throw new Error("Catalogue redirect limit");
        }
        try {
            let rows;
            if (id === "freelivesports") {
                const metadata = step("metadata", "");
                const response = await exchange({ url: metadata.url, headers: metadata.headers });
                rows = step("catalogue", response.text);
            } else {
                const input = { now: Date.now(), seed: randomBytes(32).toString("base64"), row: {}, responses: [] };
                for (let round = 0; round < 64 && Date.now() < deadline; round++) {
                    const result = step("catalogue", input);
                    if (result.done) { rows = result.value; break; }
                    if (!result.requests?.length) throw new Error("Catalogue stalled");
                    for (const request of result.requests) {
                        const response = await exchange(request);
                        input.responses.push({ request, response, completedAt: Date.now() });
                    }
                }
            }
            if (!Array.isArray(rows)) throw new Error("Invalid public catalogue");
            const prefix = id === "freelivesports" ? "enginefls" : "engine" + id;
            const inventory = rows.filter(r => typeof r.channelId === "string" && r.channelId && typeof r.name === "string").map(r => ({ name: r.name, epg_id: prefix + ":" + r.channelId, country: "", keys: [prefix + ":" + r.channelId], list: "native-" + id }));
            const oldPath = ".cache/inline-inventory-" + id + ".json";
            let oldRows = [];
            try { oldRows = JSON.parse(readFileSync(oldPath, "utf8")); } catch {}
            if (oldRows.length > 20 && inventory.length < oldRows.length / 2) throw new Error("Partial catalogue rejected");
            writeFileSync(oldPath, JSON.stringify(inventory));
            const output = nativeXml(id, rows);
            writeFileSync(root + "/" + id + ".xml.gz", gzipSync(output.xml, { mtime: 0 }));
            reports.push({ id, status: "fresh", channels: output.channels, programmes: output.programmes, requests });
        } catch (e) {
            // Preserve the prior generation cache; clear this run's native snapshot before each run.
            reports.push({ id, status: "unavailable", reason: String(e.message).replace(/https?:\/\/\S+/g, "[redacted]"), requests });
        }
    }
    writeFileSync(root + "/report.json", JSON.stringify(reports, null, 2));
    // Request/response replay journals can contain anonymous session tokens: never cache/publish them.
    rmSync(work, { recursive: true, force: true });
    console.log(JSON.stringify(reports));
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await main();
