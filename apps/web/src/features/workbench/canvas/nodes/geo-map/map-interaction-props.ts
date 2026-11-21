import type { DragEvent } from "react";
import * as stylex from "@stylexjs/stylex";

function preventMapDragStart(event: DragEvent<HTMLElement>) {
  event.preventDefault();
  event.stopPropagation();
}

export function mapInteractionProps(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    draggable: false,
    onDragStart: preventMapDragStart,
    className: `nodrag nowheel nopan${props.className ? ` ${props.className}` : ""}`,
  };
}
