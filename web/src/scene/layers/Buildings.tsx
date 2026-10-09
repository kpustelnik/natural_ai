// AGH buildings: one glb per building (contract 10.2), loaded lazily and swapped in place
// on live reload. A building is drawn in one of three ways:
//
// - massing: shell + roof, tinted by the colour mode (the campus view);
// - opened at a level (Building workspace + level stepper): levels above are hidden, the
//   roof too, and one horizontal clipping plane cuts the active level at 1.2 m, like a
//   floor plan. Cut walls show their dark inside (poché);
// - walk: every level, no clipping, so the first-person camera has floors and ceilings.

import { useEffect, useMemo } from "react";
import {
  BackSide,
  Color,
  DoubleSide,
  type Group,
  LineBasicMaterial,
  LineDashedMaterial,
  LineSegments,
  type Material,
  Mesh,
  MeshLambertMaterial,
  type Object3D,
  Plane,
  Vector3,
} from "three";
import { live, useFileVersion } from "../../data/live";
import type { Scene, SceneBuilding } from "../../generated/schemas";
import { openedBuilding, useApp } from "../../state/app";
import { useSlice } from "../../state/store";
import { buildBoundsTrees } from "../bvh";
import { ACCENT, buildingColours, SCENE, spaceColour } from "../palette";
import { noRaycast, setPickable } from "../picking";
import { useGlb } from "../useGlb";

export const SECTION_HEIGHT = 1.2; // metres above the active floor

const WHITE = new Color("#ffffff");
const ACCENT_C = new Color(ACCENT);
const ERROR_C = new Color(SCENE.error);

interface Mats {
  wall: MeshLambertMaterial;
  roof: MeshLambertMaterial;
  slab: MeshLambertMaterial;
  shellInside: MeshLambertMaterial;
  innerWall: MeshLambertMaterial;
  poche: MeshLambertMaterial;
  flight: MeshLambertMaterial;
  edge: LineBasicMaterial;
  shaft: LineDashedMaterial;
}

interface SpacePart {
  mesh: Mesh;
  key: string; // `${level}/${id}`
  id: string;
  kind: string;
  capacity: number | null;
  material: MeshLambertMaterial;
}

interface Parts {
  root: Group;
  shell: Object3D[];
  roof: Object3D[];
  edges: Object3D[];
  shaft: Object3D[];
  levels: Map<number, Object3D>;
  interior: Object3D[]; // slabs, walls, spaces, flights
  shellBacks: Mesh[];
  wallBacks: Mesh[];
  spaces: SpacePart[];
  mats: Mats;
}

function makeMaterials(): Mats {
  return {
    wall: new MeshLambertMaterial(),
    roof: new MeshLambertMaterial({ side: DoubleSide }),
    slab: new MeshLambertMaterial({ color: SCENE.slab, side: DoubleSide }),
    shellInside: new MeshLambertMaterial({ color: SCENE.shellInside, side: BackSide }),
    innerWall: new MeshLambertMaterial({ color: SCENE.innerWall }),
    poche: new MeshLambertMaterial({ color: SCENE.poche, side: BackSide }),
    flight: new MeshLambertMaterial({ color: SCENE.flight, side: DoubleSide }), // cut steps show their inside
    edge: new LineBasicMaterial({ color: SCENE.edge, transparent: true, opacity: 0.55 }),
    shaft: new LineDashedMaterial({ color: SCENE.shaft, dashSize: 1, gapSize: 0.6 }),
  };
}

export function disposeParts(parts: Parts): void {
  Object.values(parts.mats).forEach((m: Material) => m.dispose());
  parts.spaces.forEach((sp) => sp.material.dispose());
}

/** Adds a mesh drawing the back faces of `m` (same geometry) and returns it. */
function backFaces(m: Mesh, material: Material): Mesh {
  const back = new Mesh(m.geometry, material);
  back.userData.back = true;
  noRaycast(back);
  m.add(back);
  return back;
}

// Parts are prepared once per loaded glb: materials are assigned to its meshes, so this
// must not run twice for one scene (React may call memos twice in dev).
const prepared = new WeakMap<Group, Parts>();

function prepare(scene: Group, bid: string): Parts {
  const done = prepared.get(scene);
  if (done) return done;
  const mats = makeMaterials();
  const parts: Parts = {
    mats,
    root: scene,
    shell: [],
    roof: [],
    edges: [],
    shaft: [],
    levels: new Map(),
    interior: [],
    shellBacks: [],
    wallBacks: [],
    spaces: [],
  };
  const meshes: Object3D[] = [];
  scene.traverse((o) => meshes.push(o));
  for (const o of meshes) {
    const d = o.userData;
    const part = d.part as string | undefined;
    if (part === undefined && typeof d.level === "number") parts.levels.set(d.level, o);
    if (o instanceof Mesh) {
      if (part === "shell") {
        o.material = mats.wall;
        parts.shell.push(o);
        parts.shellBacks.push(backFaces(o, mats.shellInside));
      } else if (part === "roof") {
        o.material = mats.roof;
        parts.roof.push(o);
      } else if (part === "slab") {
        o.material = mats.slab;
        parts.interior.push(o);
      } else if (part === "walls") {
        o.material = mats.innerWall;
        parts.interior.push(o);
        parts.wallBacks.push(backFaces(o, mats.poche));
      } else if (part === "space" || part === "flight") {
        const material = part === "flight" ? mats.flight : new MeshLambertMaterial();
        o.material = material;
        parts.interior.push(o);
        const level = d.level as number;
        const id = String(d.id);
        setPickable(o, () => ({ kind: "space", building: bid, id, level }));
        if (part === "space") {
          parts.spaces.push({
            mesh: o,
            key: `${level}/${id}`,
            id,
            kind: String(d.kind),
            capacity: typeof d.capacity === "number" ? d.capacity : null,
            material,
          });
        }
      }
    } else if (o instanceof LineSegments) {
      noRaycast(o);
      if (part === "shaft") {
        o.material = mats.shaft;
        o.computeLineDistances();
        parts.shaft.push(o);
      } else {
        o.material = mats.edge;
        parts.edges.push(o);
      }
    }
  }
  setPickable(scene, () => ({ kind: "building", id: bid }));
  buildBoundsTrees(scene);
  prepared.set(scene, parts);
  return parts;
}

type View = "massing" | "level" | "walk";

function BuildingModel({ b }: { b: SceneBuilding }) {
  const version = useFileVersion(b.glb);
  const scene = useGlb(b.glb, version);
  const colorMode = useApp((s) => s.colorMode);
  const roomColor = useApp((s) => s.roomColor);
  const selected = useApp((s) => s.selection?.kind === "building" && s.selection.id === b.id);
  const hovered = useApp((s) => s.hover?.kind === "building" && s.hover.id === b.id);
  const opened = useApp((s) => openedBuilding(s) === b.id);
  const ghost = useApp((s) => {
    const o = openedBuilding(s);
    return s.camera !== "walk" && o !== null && o !== b.id;
  });
  const level = useApp((s) => (openedBuilding(s) === b.id ? s.level : null));
  const walking = useApp((s) => s.camera === "walk");
  const selSpace = useApp((s) =>
    s.selection?.kind === "space" && s.selection.building === b.id ? `${s.selection.level}/${s.selection.id}` : null,
  );
  const hoverSpace = useApp((s) =>
    s.hover?.kind === "space" && s.hover.building === b.id ? `${s.hover.level}/${s.hover.id}` : null,
  );
  const errorKey = useSlice(live, (s) =>
    (s.status?.errors ?? [])
      .filter((e) => e.building_id === b.id && e.element)
      .map((e) => e.element)
      .join("|"),
  );

  const parts = useMemo(() => (scene ? prepare(scene, b.id) : null), [scene, b.id]);
  const mats = parts?.mats;
  // free the GPU programs when this glb is replaced (live reload) or the layer unmounts
  useEffect(
    () => () => {
      if (parts) disposeParts(parts);
    },
    [parts],
  );

  const view: View = !opened ? "massing" : walking ? "walk" : level !== null ? "level" : "massing";
  const floor = b.levels.find((l) => l.id === level);
  const cutY = view === "level" && floor ? floor.floor_y + SECTION_HEIGHT : null;

  // visibility and clipping
  useEffect(() => {
    if (!parts) return;
    const showInterior = view !== "massing";
    const set = (objs: Object3D[], on: boolean) => objs.forEach((o) => (o.visible = on));
    set(parts.shell, view !== "level" || b.lod === 1);
    set(parts.roof, view !== "level");
    set(parts.edges, view !== "walk");
    set(parts.shaft, opened && view !== "walk");
    set(parts.interior, showInterior);
    set(parts.shellBacks, showInterior);
    set(parts.wallBacks, showInterior);
    for (const [id, group] of parts.levels) group.visible = view === "walk" || (view === "level" && level !== null && id <= level);

    const planes = cutY !== null ? [new Plane(new Vector3(0, -1, 0), cutY)] : [];
    const all: Material[] = [...Object.values(parts.mats), ...parts.spaces.map((s) => s.material)];
    for (const m of all) {
      m.clippingPlanes = planes;
      m.needsUpdate = true;
    }
    parts.root.userData.clipY = cutY ?? undefined;
  }, [parts, view, level, cutY, opened, b.lod]);

  // colours
  useEffect(() => {
    if (!mats) return;
    const base = buildingColours(b, colorMode);
    const tint = (c: string) => {
      const col = new Color(c);
      if (selected) col.lerp(ACCENT_C, 0.3);
      else if (hovered) col.lerp(WHITE, 0.55);
      return col;
    };
    mats.wall.color.copy(tint(base.wall));
    mats.roof.color.copy(tint(base.roof));
    mats.edge.color.set(selected ? ACCENT : SCENE.edge);
    mats.edge.opacity = selected ? 0.95 : 0.55;
    for (const m of [mats.wall, mats.roof]) {
      m.transparent = ghost;
      m.opacity = ghost ? 0.12 : 1;
      m.depthWrite = !ghost;
      m.needsUpdate = true;
    }
    if (ghost) mats.edge.opacity = 0.12;
  }, [b, colorMode, selected, hovered, ghost, mats]);

  // spaces: kind or capacity, selection, hover, validation errors
  useEffect(() => {
    if (!parts) return;
    const errors = new Set(errorKey ? errorKey.split("|") : []);
    for (const s of parts.spaces) {
      const col = new Color(spaceColour(s.kind, s.capacity, roomColor));
      if (errors.has(s.id)) col.lerp(ERROR_C, 0.75);
      if (s.key === selSpace) col.lerp(ACCENT_C, 0.45);
      else if (s.key === hoverSpace) col.lerp(ACCENT_C, 0.15);
      s.material.color.copy(col);
    }
  }, [parts, roomColor, selSpace, hoverSpace, errorKey]);

  return parts ? <primitive object={parts.root} /> : null;
}

export function Buildings({ scene }: { scene: Scene }) {
  return (
    <group>
      {scene.buildings.map((b) => (
        <BuildingModel key={b.id} b={b} />
      ))}
    </group>
  );
}
