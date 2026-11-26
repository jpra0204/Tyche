// The kill switch and resume, each confirmed in the page and then run as the CLI
// command with --yes, as it would be after answering its own question.
import { Alert, Button, Checkbox, Group, List, Modal, Stack, Text, TextInput } from "@mantine/core";
import { IconHandStop, IconPlayerPlay } from "@tabler/icons-react";
import { useState } from "react";

import type { TradingView } from "../../api/types";
import { ErrorAlert } from "../../components/ErrorAlert";
import { useStartRun } from "../runs/useRun";

function KillModal({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  const start = useStartRun();
  const [reason, setReason] = useState("");
  const [flatten, setFlatten] = useState(false);
  const [understood, setUnderstood] = useState(false);
  const ready = reason.trim() !== "" && (!flatten || understood);

  function close() {
    setFlatten(false);
    setUnderstood(false);
    onClose();
  }

  return (
    <Modal opened={opened} onClose={close} title="Engage the kill switch?" size="lg">
      <Stack gap="sm">
        <Text size="sm">
          No new orders from the next decision on. Holdings are kept and stops already resting
          stay. Orders already working at IBKR are not cancelled. Only resume releases it.
        </Text>
        <TextInput
          label="Reason"
          description="For the journal, the alert, and you later"
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
          maxLength={300}
          required
          data-autofocus
        />
        <Checkbox
          label="Also flatten: sell every holding at the next decision"
          checked={flatten}
          onChange={(event) => {
            setFlatten(event.currentTarget.checked);
            setUnderstood(false);
          }}
        />
        {flatten && (
          <Alert color="red" title="Flatten sells everything">
            At the next decision, each holding's stop is cancelled and the holding is sold at
            the open.
            <Checkbox
              mt="sm"
              label="I want every holding sold"
              checked={understood}
              onChange={(event) => setUnderstood(event.currentTarget.checked)}
            />
          </Alert>
        )}
        {start.isError && <ErrorAlert error={start.error} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={close}>
            Cancel
          </Button>
          <Button
            color="red"
            disabled={!ready}
            loading={start.isPending}
            onClick={() =>
              start.mutate(
                { command: "kill", reason: reason.trim(), flatten, confirmed: true },
                { onSuccess: close },
              )
            }
          >
            {flatten ? "Engage and flatten" : "Engage the kill switch"}
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

function ResumeModal({
  opened,
  onClose,
  trading,
}: {
  opened: boolean;
  onClose: () => void;
  trading: TradingView;
}) {
  const start = useStartRun();
  const [reason, setReason] = useState("");

  return (
    <Modal opened={opened} onClose={onClose} title="Lift the stop and trade again?" size="lg">
      <Stack gap="sm">
        <Text size="sm">This lifts:</Text>
        <List size="sm" spacing={4}>
          {trading.kill && <List.Item>the kill switch ({trading.kill.reason});</List.Item>}
          {trading.drawdown_halt && (
            <List.Item>
              the drawdown halt: Tyche forgets the peak, and the next close becomes the new peak;
            </List.Item>
          )}
          {trading.reconciliation_halt && (
            <List.Item>
              the reconciliation halt, applying any fills it explained and taking the broker's
              cash as the halt recorded it. Its differences:
              <List size="xs" withPadding>
                {trading.reconciliation_halt.reasons.map((r) => (
                  <List.Item key={r}>{r}</List.Item>
                ))}
              </List>
            </List.Item>
          )}
        </List>
        <Text size="sm">The next decision then trades normally.</Text>
        <Text size="xs" c="dimmed">
          Resume is yours alone. Follow the runbook first: understand why it stopped.
        </Text>
        <TextInput
          label="Reason"
          description="Why trading may start again, for the journal"
          value={reason}
          onChange={(event) => setReason(event.currentTarget.value)}
          maxLength={300}
          required
          data-autofocus
        />
        {start.isError && <ErrorAlert error={start.error} />}
        <Group justify="flex-end">
          <Button variant="default" onClick={onClose}>
            Cancel
          </Button>
          <Button
            color="green"
            disabled={reason.trim() === ""}
            loading={start.isPending}
            onClick={() =>
              start.mutate(
                { command: "resume", reason: reason.trim(), confirmed: true },
                { onSuccess: onClose },
              )
            }
          >
            Lift it and trade again
          </Button>
        </Group>
      </Stack>
    </Modal>
  );
}

export function StopControls({ trading, running }: { trading: TradingView; running: boolean }) {
  const [killing, setKilling] = useState(false);
  const [resuming, setResuming] = useState(false);
  const unreadable = trading.state_unreadable !== null && trading.state_unreadable !== undefined;

  return (
    <Group>
      <Button
        color="red"
        variant="light"
        leftSection={<IconHandStop size={16} />}
        disabled={running}
        onClick={() => setKilling(true)}
      >
        Kill switch…
      </Button>
      <Button
        color="green"
        variant="light"
        leftSection={<IconPlayerPlay size={16} />}
        disabled={running || !trading.stopped || unreadable}
        onClick={() => setResuming(true)}
      >
        Resume…
      </Button>
      <KillModal opened={killing} onClose={() => setKilling(false)} />
      <ResumeModal opened={resuming} onClose={() => setResuming(false)} trading={trading} />
    </Group>
  );
}
