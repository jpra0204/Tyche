// Parsed settings shown as nested tables: what a file holds, read-only.
import { Code, Table, Text } from "@mantine/core";

function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined) {
    return (
      <Text span c="dimmed" fz="sm">
        none
      </Text>
    );
  }
  if (Array.isArray(value)) {
    if (value.every((v) => typeof v !== "object" || v === null)) {
      return <Code>{value.map((v) => String(v)).join(", ")}</Code>;
    }
    return (
      <>
        {value.map((v, i) => (
          <Settings key={i} settings={v as Record<string, unknown>} />
        ))}
      </>
    );
  }
  if (typeof value === "object") {
    return <Settings settings={value as Record<string, unknown>} />;
  }
  return <Code>{String(value)}</Code>;
}

export function Settings({ settings }: { settings: Record<string, unknown> }) {
  const keys = Object.keys(settings);
  if (keys.length === 0) {
    return (
      <Text size="sm" c="dimmed">
        empty
      </Text>
    );
  }
  return (
    <Table fz="sm" verticalSpacing={4} withRowBorders={false}>
      <Table.Tbody>
        {keys.map((key) => (
          <Table.Tr key={key}>
            <Table.Td w={220} c="dimmed" style={{ verticalAlign: "top" }}>
              {key}
            </Table.Td>
            <Table.Td>
              <Value value={settings[key]} />
            </Table.Td>
          </Table.Tr>
        ))}
      </Table.Tbody>
    </Table>
  );
}
