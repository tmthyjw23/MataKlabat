// Leaflet map: three base layers (Spec §10.3) and live overlays.
"use strict";

const SPREAD_HALF_ANGLE = 45; // same sector as the agent's estimate_spread tool
const SPREAD_RADIUS_KM = 8;

const BASE_LAYERS = {
  "Topografi": {
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    options: {
      subdomains: "abc",
      maxZoom: 17,
      attribution: 'Kartendaten: © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>-Mitwirkende, SRTM | Kartendarstellung: © <a href="https://opentopomap.org">OpenTopoMap</a> (<a href="https://creativecommons.org/licenses/by-sa/3.0/">CC-BY-SA</a>)',
    },
  },
  "Satelit": {
    url: "https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/{z}/{y}/{x}.jpg",
    options: {
      maxZoom: 17,
      attribution: '<a href="https://s2maps.eu">Sentinel-2 cloudless - https://s2maps.eu</a> by <a href="https://eox.at">EOX IT Services GmbH</a> (Contains modified Copernicus Sentinel data 2024)',
    },
  },
  "Jalan": {
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    options: {
      maxZoom: 19,
      attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    },
  },
};

function destination(lat, lon, bearingDeg, km) {
  const R = 6371;
  const d = km / R;
  const b = (bearingDeg * Math.PI) / 180;
  const p1 = (lat * Math.PI) / 180;
  const l1 = (lon * Math.PI) / 180;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return [(p2 * 180) / Math.PI, (l2 * 180) / Math.PI];
}

class MapView {
  constructor(element) {
    this.map = L.map(element, { scrollWheelZoom: false });
    const layers = {};
    for (const [name, def] of Object.entries(BASE_LAYERS)) {
      layers[name] = L.tileLayer(def.url, { ...def.options, referrerPolicy: "strict-origin-when-cross-origin" });
    }
    layers["Topografi"].addTo(this.map);
    L.control.layers(layers, null, { position: "topright" }).addTo(this.map);
    L.control.scale({ imperial: false }).addTo(this.map);
    this.cameraLayer = L.layerGroup().addTo(this.map);
    this.spreadLayer = L.layerGroup().addTo(this.map);
    this.hotspotLayer = L.layerGroup().addTo(this.map);
    this.windControl = null;
    this.map.setView([1.45304, 125.03121], 12);
    // The card (and so the map) grows when the incident panel renders next to it.
    new ResizeObserver(() => this.map.invalidateSize()).observe(element);
  }

  setStatic(data) {
    this.map.setView(data.center, 12);
    const places = L.layerGroup().addTo(this.map);
    for (const v of data.villages) {
      L.circleMarker([v.lat, v.lon], { radius: 4, color: "#1d2722", weight: 1, fillColor: "#fff", fillOpacity: 1 })
        .bindTooltip(h("span", { text: v.name }), { permanent: true, direction: "right", className: "place-label", offset: [6, 0] })
        .addTo(places);
    }
    for (const p of data.reference_points) {
      const label = h("span", { class: "place-label" }, "▲ ", p.name);
      L.marker([p.lat, p.lon], { icon: L.divIcon({ html: label, className: "", iconSize: null }), keyboard: false })
        .addTo(places);
    }
    for (const r of data.resources) {
      L.circleMarker([r.lat, r.lon], { radius: 5, color: "#1d4e89", weight: 2, fillColor: "#fff", fillOpacity: 1 })
        .bindTooltip(h("span", { text: `${r.name} (${r.kind})` }))
        .addTo(places);
    }
  }

  update(status) {
    this.cameraLayer.clearLayers();
    this.spreadLayer.clearLayers();
    const now = (status.risk && status.risk.now) || {};
    for (const cam of status.cameras) {
      const kind = cameraKind(cam);
      const marker = h("span", { class: `cam-marker ${kind}` }, statusIcon(kind, 16), cam.id);
      const popup = h("div", null,
        h("strong", { text: `${cam.id} · ${cam.name}` }), h("br"),
        STATUS[kind].label,
        cam.sub_status ? ` (${SUB_STATUS[cam.sub_status] || cam.sub_status})` : "",
      );
      L.marker([cam.lat, cam.lon], {
        icon: L.divIcon({ html: marker, className: "", iconSize: null, iconAnchor: [10, 12] }),
        title: `${cam.id} ${STATUS[kind].label}`,
        alt: `${cam.id} ${STATUS[kind].label}`,
      }).bindPopup(popup).addTo(this.cameraLayer);

      if ((kind === "fire" || kind === "check") && now.wind_dir_deg !== null && now.wind_dir_deg !== undefined) {
        const toward = (now.wind_dir_deg + 180) % 360;
        const points = [[cam.lat, cam.lon]];
        for (let a = -SPREAD_HALF_ANGLE; a <= SPREAD_HALF_ANGLE; a += 5) {
          points.push(destination(cam.lat, cam.lon, toward + a, SPREAD_RADIUS_KM));
        }
        const color = kind === "fire" ? "#b42318" : "#b45309";
        L.polygon(points, { color, weight: 1, fillColor: color, fillOpacity: 0.12, interactive: false })
          .addTo(this.spreadLayer);
      }
    }
    this.setWind(now);
  }

  setWind(now) {
    if (now.wind_dir_deg === null || now.wind_dir_deg === undefined) return;
    if (!this.windControl) {
      const Wind = L.Control.extend({
        onAdd: () => {
          this.windArrow = svg("svg", { class: "wind-arrow", viewBox: "0 0 28 28", "aria-hidden": "true" },
            svg("path", { d: "M14 25V4M8 10l6-6 6 6", fill: "none", stroke: "currentColor", "stroke-width": 2.5, "stroke-linecap": "round" }));
          this.windText = h("div", { class: "small" });
          return h("div", { class: "wind-control" }, this.windArrow, this.windText);
        },
      });
      this.windControl = new Wind({ position: "bottomright" }).addTo(this.map);
    }
    const toward = (now.wind_dir_deg + 180) % 360;
    this.windArrow.style.transform = `rotate(${toward}deg)`;
    replace(this.windText,
      h("div", { text: `Angin dari ${compass(now.wind_dir_deg)}` }),
      h("strong", { text: `${num(now.wind_kmh, 0)} km/j → ke ${compass(toward)}` }),
    );
  }

  setHotspots(result, note) {
    this.hotspotLayer.clearLayers();
    if (!result || result.status !== "ok") {
      note.textContent = `Hotspot satelit (NASA FIRMS): ${result && result.reason ? result.reason : "tidak tersedia"}`;
      return;
    }
    for (const spot of result.hotspots) {
      L.circleMarker([spot.lat, spot.lon], { radius: 7, color: "#7a1a12", weight: 2, fillColor: "#f97316", fillOpacity: 0.9 })
        .bindTooltip(h("span", { text: `Hotspot ${spot.time_utc} UTC, ±${spot.distance_km} km` }))
        .addTo(this.hotspotLayer);
    }
    note.textContent = result.count
      ? `Hotspot satelit 24 jam: ${result.count} titik`
      : "Hotspot satelit (NASA FIRMS): tidak ada dalam 24 jam";
  }
}
