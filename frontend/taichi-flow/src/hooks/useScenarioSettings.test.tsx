import { fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider, useLocation } from "react-router-dom";
import { expect, it } from "vitest";
import { useScenarioSettings } from "./useScenarioSettings";

function Screen() {
  const settings = useScenarioSettings();
  const location = useLocation();
  return <><p>{location.pathname + location.search}</p><button onClick={settings.isSettings ? settings.returnFromSettings : settings.openSettings}>齿轮</button></>;
}
const editor = "/editor/p/scenarios/s";
function setup(entry: string | { pathname: string; state: unknown }) {
  render(<RouterProvider router={createMemoryRouter([
    { path: "/editor/:projectId/scenarios/:scenarioId", element: <Screen /> },
    { path: "/editor/:projectId/scenarios/:scenarioId/settings", element: <Screen /> },
  ], { initialEntries: [entry] })} />);
}
it("restores the exact query and inspector tab", async () => {
  setup(editor + "?inspector=run&dock=queue");
  fireEvent.click(screen.getByText("齿轮"));
  expect(await screen.findByText(editor + "/settings")).toBeInTheDocument();
  fireEvent.click(screen.getByText("齿轮"));
  expect(await screen.findByText(editor + "?inspector=run&dock=queue")).toBeInTheDocument();
});
it("rejects an unrelated return path and returns to this scenario", async () => {
  setup({ pathname: editor + "/settings", state: { settingsReturnTo: "/editor/other/scenarios/other" } });
  fireEvent.click(screen.getByText("齿轮"));
  expect(await screen.findByText(editor)).toBeInTheDocument();
});
