# Canvas lab and sandbox

The workbench and sandbox use one Canvas lab panel. Its shared registry owns
the canvas control labels, values, and URL codecs. The sandbox supplies a Nodes tab alongside the shared Canvas controls.
Its picker composes versioned catalog nodes into one authored graph. The
fixture includes the schema connection whenever both endpoints are visible.

Canvas appearance and pipe routing are development controls. The normal
workbench uses shipped defaults and honours an existing saved grid preference.
A development URL can override those values without writing to browser
storage. Theme belongs in app chrome. A sandbox URL can override it for the
fixture without changing the app preference.

The sandbox owns authored fixtures and captured catalog data. It passes them
through `cellGraphFromAuthoredDocument`, the adapter used by the workbench.
Cards require the surfaces produced by that adapter. A second card renderer
would let the sandbox pass visual checks while the workbench draws different
ports and wells. Router stress fixtures belong alongside router tests.

Development sessions are for render fixtures. The sandbox uses the existing
stand-in session and a captured registry. A real Workspace still uses the
normal authenticated workbench. Canvas query parameters configure rendering
and leave Workspace capabilities in force.

The [Canvas lab reference](../agents/web-canvas.md) describes the URL and
geometry contracts. The [sandbox charter](../../apps/web/src/sandbox/README.md)
describes when to add and remove a spike.
