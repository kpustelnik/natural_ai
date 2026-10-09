// Split view of a simulation: the scene is drawn twice per frame with one shared camera,
// no metro on the left half and with metro on the right. Objects registered for one side
// (registry.split) are hidden on the other. Pointer events map into the half they are in,
// so picking and hover work on both sides.

import { type EventManager, events, type RootStore, useFrame } from "@react-three/fiber";
import { app, splitActive } from "../state/app";
import { registry } from "./registry";

export function SplitRenderer() {
  // a positive priority takes over R3F's render: this callback draws the frame
  useFrame(({ gl, scene, camera, size }) => {
    const w = Math.floor(size.width / 2);
    const { left, right } = registry.split;
    const pass = (x: number, width: number, onLeft: boolean) => {
      for (const o of left) o.visible = onLeft;
      for (const o of right) o.visible = !onLeft;
      gl.setViewport(x, 0, width, size.height);
      gl.setScissor(x, 0, width, size.height);
      gl.render(scene, camera);
    };
    gl.setScissorTest(true);
    pass(0, w, true);
    pass(w, size.width - w, false);
    gl.setScissorTest(false);
    gl.setViewport(0, 0, size.width, size.height);
    for (const o of left) o.visible = true;
    for (const o of right) o.visible = true;
  }, 1);
  return null;
}

/** R3F's pointer events, with the pointer measured in its half while the view is split. */
export function splitEvents(store: RootStore): EventManager<HTMLElement> {
  const base = events(store);
  return {
    ...base,
    compute(event, state) {
      const split = splitActive(app.get());
      const w = split ? Math.floor(state.size.width / 2) : state.size.width;
      const x = split && event.offsetX >= w ? event.offsetX - w : event.offsetX;
      state.pointer.set((x / w) * 2 - 1, -(event.offsetY / state.size.height) * 2 + 1);
      state.raycaster.setFromCamera(state.pointer, state.camera);
    },
  };
}
