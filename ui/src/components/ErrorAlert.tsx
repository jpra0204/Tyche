import { Alert } from "@mantine/core";
import { IconAlertTriangle } from "@tabler/icons-react";

import { ApiError } from "../api/client";

export function ErrorAlert({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  const unauthorised = error instanceof ApiError && error.status === 401;
  return (
    <Alert color="red" icon={<IconAlertTriangle />} title="The console could not read Tyche">
      {unauthorised
        ? "The console's key does not match this launch. Open the address `tyche ui` printed."
        : message}
    </Alert>
  );
}
