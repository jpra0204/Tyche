// In the header on every page: which command is running, if one is.
import { Badge, Loader } from "@mantine/core";

import { useCurrentRun } from "./useRun";

export function RunIndicator() {
  const run = useCurrentRun().data;
  if (run?.state !== "running") return null;
  return (
    <Badge variant="light" color="blue" leftSection={<Loader size={10} />} tt="none">
      Running: {run.argv.slice(0, 3).join(" ")}
    </Badge>
  );
}
