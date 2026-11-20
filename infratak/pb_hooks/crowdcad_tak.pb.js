/// <reference path="../pb_data/types.d.ts" />
// CrowdCAD for TAK: compare-and-swap writes for the bridge's native dispatch.
//
// Installed by `install.sh --with-crowdcad` into the PocketBase it runs (mounted at
// /pb/pb_hooks). CrowdCAD itself is unmodified and never calls these routes.
//
// CrowdCAD keeps a whole event (calls, teams, supervisors, equipment) in one record and saves
// it with read-then-PATCH, so a plain PATCH from the bridge could silently overwrite a change a
// dispatcher made a moment earlier. This route applies the bridge's change only if the fields
// it read are still exactly what it read, all inside one transaction; otherwise 409 and the
// bridge re-reads and re-applies (bridge/crowdcad_tak/store.py).
//
// It never widens access: the caller must be a signed-in CrowdCAD user, the write is checked
// against the events collection's own updateRule exactly like a REST PATCH, ended events are
// refused (CrowdCAD's isEventEnded check), and only the four dispatch fields can be written.

routerAdd("GET", "/api/crowdcad-tak/ping", (e) => {
    return e.json(200, { ok: true, hook: "crowdcad-tak", version: 1 });
});

routerAdd("POST", "/api/crowdcad-tak/events/{id}/apply", (e) => {
    // Handlers run in isolated VMs: everything they use is defined in here.
    const FIELDS = ["calls", "staff", "supervisor", "eventEquipment"];

    function canonical(value) {
        if (Array.isArray(value)) return value.map(canonical);
        if (value && typeof value === "object") {
            const out = {};
            Object.keys(value).sort().forEach((k) => { out[k] = canonical(value[k]); });
            return out;
        }
        return value === undefined ? null : value;
    }
    function same(a, b) {
        return JSON.stringify(canonical(a)) === JSON.stringify(canonical(b));
    }
    function stored(record, key) {
        const raw = record.getString(key);
        if (!raw || raw === "null") return null;
        try { return JSON.parse(raw); } catch (_) { return null; }
    }

    const id = e.request.pathValue("id");
    const info = e.requestInfo();
    const body = JSON.parse(JSON.stringify(info.body || {}));   // plain JS values, not Go maps
    const expect = body._expect;
    if (!expect || typeof expect !== "object") {
        throw new BadRequestError("_expect is required");
    }
    const patch = {};
    Object.keys(body).forEach((key) => {
        if (key === "_expect") return;
        if (FIELDS.indexOf(key) < 0) throw new BadRequestError("field not allowed: " + key);
        patch[key] = body[key];
    });
    Object.keys(expect).forEach((key) => {
        if (FIELDS.indexOf(key) < 0) throw new BadRequestError("field not allowed in _expect: " + key);
    });
    if (!Object.keys(patch).length) throw new BadRequestError("nothing to write");

    let conflict = null;
    $app.runInTransaction((txApp) => {
        const record = txApp.findRecordById("events", id);
        if (!txApp.canAccessRecord(record, info, record.collection().updateRule)) {
            throw new ForbiddenError("This CrowdCAD account can't dispatch this event (share it with the bridge account or make it an org event).");
        }
        if (record.getBool("ended")) {
            conflict = { error: "ended", message: "This event has ended." };
            return;
        }
        for (const key of Object.keys(expect)) {
            if (!same(stored(record, key), expect[key])) {
                conflict = { error: "changed", field: key, message: "The event changed since it was read." };
                return;
            }
        }
        Object.keys(patch).forEach((key) => record.set(key, patch[key]));
        txApp.save(record);
    });
    if (conflict) return e.json(409, conflict);
    return e.json(200, { ok: true });
}, $apis.requireAuth("users"));
