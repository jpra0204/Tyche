// A report.html (a backtest's or a study's) inside the page, in a sandboxed frame: no
// script runs in it (reports have none, and without `allow-scripts` none could), no form.
//
// The file is shown from a blob: address, not `srcdoc`: a `srcdoc` document resolves
// its links against the console's address, so the report's table of contents would
// load the console inside the frame. `allow-same-origin` lets those links move within
// the blob document; without scripts it gives the report no way to read the console.
import { useEffect, useRef } from "react";

// The frame's address is set here, outside React's state: it is a resource to make
// and release with the html, like a subscription.
export function ReportFrame({ html, title }: { html: string; title: string }) {
  const frame = useRef<HTMLIFrameElement>(null);
  useEffect(() => {
    const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    if (frame.current) frame.current.src = url;
    return () => URL.revokeObjectURL(url);
  }, [html]);
  return (
    <iframe
      ref={frame}
      title={title}
      sandbox="allow-same-origin"
      style={{
        width: "100%",
        height: "calc(100vh - 170px)",
        border: "1px solid var(--mantine-color-default-border)",
        borderRadius: "var(--mantine-radius-md)",
        background: "white",
      }}
    />
  );
}
