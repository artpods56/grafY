const XLINK_NAMESPACE = "http://www.w3.org/1999/xlink";

/** How many parses it may take for the HTML to come back unchanged. */
const MAX_SWEEPS = 4;

/**
 * A sandboxed frame can still navigate itself, and a link is enough to carry this
 * page's data out in the URL. Hash links stay, because they only move inside the frame.
 * Everything else that can become a link or reach out goes:
 *
 * - a declarative shadow root, because a template's content is out of a sweep's reach
 *   here and turns into live links when the frame parses it;
 * - an SVG animation of `href`, which writes the address after this sweep has run;
 * - `link`, because a `dns-prefetch` can reach out where the policy may not look.
 *
 * Serialising and parsing again can change what HTML means, so the sweep repeats until
 * it changes nothing. HTML that never settles is not shown at all.
 */
export function disarmFrameHtml(html: string): string {
  if (typeof DOMParser === "undefined") return "";
  let current = html;
  for (let sweep = 0; sweep < MAX_SWEEPS; sweep += 1) {
    const next = sweepFrameHtml(current);
    if (next === current) return current;
    current = next;
  }
  return "";
}

function sweepFrameHtml(html: string): string {
  const document = new DOMParser().parseFromString(html, "text/html");
  for (const element of document.querySelectorAll("base, link, template")) {
    element.remove();
  }
  for (const animation of document.querySelectorAll("animate, set")) {
    if (/href/i.test(animation.getAttribute("attributeName") ?? "")) {
      animation.remove();
    }
  }
  for (const element of document.querySelectorAll("*")) {
    element.removeAttribute("target");
    // An SVG image's address is only ever an image, which the frame's policy governs.
    if (element.localName === "image") continue;
    dropRemoteHref(element, "href");
    dropRemoteHref(element, "xlink:href");
    const namespaced = element.getAttributeNS(XLINK_NAMESPACE, "href");
    if (namespaced !== null && !namespaced.startsWith("#")) {
      element.removeAttributeNS(XLINK_NAMESPACE, "href");
    }
  }
  // A fragment has to come back as a fragment. Wrapping a bare table in a
  // document would send it through the frame, and the card draws that table
  // as its own elements.
  if (/^\s*(?:<!doctype\b|<html\b|<head\b|<body\b)/i.test(html)) {
    return document.documentElement.outerHTML;
  }
  return document.body.innerHTML;
}

function dropRemoteHref(element: Element, name: string) {
  const href = element.getAttribute(name);
  if (href !== null && !href.startsWith("#")) element.removeAttribute(name);
}
