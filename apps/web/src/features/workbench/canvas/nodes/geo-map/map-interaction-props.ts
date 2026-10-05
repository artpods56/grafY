import * as stylex from "@stylexjs/stylex";

export function mapInteractionProps(props: ReturnType<typeof stylex.props>) {
  return {
    ...props,
    className: `nodrag nowheel nopan${props.className ? ` ${props.className}` : ""}`,
  };
}
