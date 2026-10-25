import test from "node:test";
import assert from "node:assert/strict";
import { nativeXml } from "../tools/native-guides.mjs";

test("public inline programmes retain exact MovieHub ids without stream URLs", () => {
    const now = Date.now();
    const value = nativeXml("freelivesports", [{ channelId: "sport", name: "Sport & News", streamUrl: "https://example.test/private-token", programs: [{ title: "Live", start: new Date(now - 1000).toISOString(), end: new Date(now + 60000).toISOString() }] }], now);
    assert.match(value.xml, /enginefls:sport/);
    assert.match(value.xml, /Sport &amp; News/);
    assert.ok(!value.xml.includes("private-token"));
    assert.equal(value.programmes, 1);
});

test("expired inline programmes are not shifted forward", () => {
    assert.throws(() => nativeXml("stirr", [{ channelId: "one", programs: [{ title: "Old", start: "2000-01-01T00:00:00Z", end: "2000-01-01T01:00:00Z" }] }]), /No usable/);
});
