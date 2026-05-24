import { getServiceUrl } from "./urlConfig.js";

export async function getPickSheet() {
  const lambdaURL = await getServiceUrl("getPickSheet");
  const response = await fetch(lambdaURL, {
    method: "GET",
    headers: { "Content-Type": "application/json" },
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`);
  }

  return response.json(); // parse JSON directly
}

// Source - https://stackoverflow.com/a/60377870
// Posted by dabeng
// Retrieved 2026-03-25, License - CC BY-SA 4.0

export function export2txt(picksData) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([JSON.stringify(picksData, null, 2)], {
    type: "application/json"
  }));
  console.log("Generated blob URL:", a.href);
  a.setAttribute("download", "picks.json");
  document.body.appendChild(a);
  a.click();
  console.log("Download triggered for picks.json");
  document.body.removeChild(a);
}

export function savePicksToFile(picksString) {
  console.log("Saving picks to file:", picksString);
  const blob = new Blob([picksString], { type: "application/json" });
  saveAs
  const url = URL.createObjectURL(blob);
  console.log("Generated blob URL:", url);
  const a = document.createElement("a");
  a.href = url;
  a.download = "/fbp-admin/picks.json";
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export function renderPickSheet(items) {
  return items
    .filter(
      (item) =>
        item &&
        item.GameId &&
        item.Away &&
        item.Home &&
        item.Underdog &&
        item.Spread,
    ) // adjust criteria as needed
    .map((item, index) => {
      const gameClass = index % 2 === 0 ? "game-even" : "game-odd";
      const spreadRow =
        item.Underdog === "H"
          ? `
          <tr>
            <td></td>
            <td></td>
            <td id="${item.GameId}-H">+${item.Spread}</td>
            <td></td>
          </tr>`
          : item.Underdog === "A"
            ? `
          <tr>
            <td></td>
            <td id="${item.GameId}-A">+${item.Spread}</td>
            <td></td>
            <td></td>
          </tr>`
            : "";

      return `
      <tr class="${gameClass}">
        <td> 
          <label class="container">
            <input type="radio" name="${item.GameId}" value="A">
            <span class="checkmark"></span>
          </label>
        </td>
        <td> <img src="/images/${item.Away}.gif" alt="" width="30" height="30">
        </td>
        <td> <img src="/images/${item.Home}.gif" alt="" width="30" height="30">
        </td>
        <td style="text-align:center" class="fa fa-align-center" aria-hidden="true">
          <label class="container">
            <input type="radio" name="${item.GameId}" value="H">
            <span class="checkmark"></span>
          </label>
        </td>
      </tr>
      <tr class="${gameClass}">
        <td></td>
        <td>${item.Away}</td>
        <td>${item.Home}</td>
        <td></td>
      </tr>
      ${spreadRow.replace('<tr>', `<tr class="${gameClass}">`)}
    `;
      // Can I push the monday night tie breaker in here?
    })
    .join("");
}

export function getHomeandAwayPicks(checkBoxName) {
  const checkboxes = document.getElementsByName(checkBoxName);
  let picks = [];
  checkboxes.forEach((checkbox) => {
    if (checkbox.checked) {
      picks.push(checkbox.value);
    }
  });
  return picks;
}

export function getCheckedRadioPicks(formId) {
  const form = document.getElementById(formId);

  const checkedRadios = form.querySelectorAll('input[type="radio"]:checked');

  // returns one entry per game (because each game has its own radio group name)
  return Array.from(checkedRadios, (r) => ({
    gameId: r.name.replace(/^pick_/, ""), // if you used name="pick_<GameId>"
    value: r.value, // e.g. "123A" or "123H"
  }));
}

export function getPicks(formId) {
  const form = document.getElementById(formId);

  // Find the first radio in each game group in DOM order.
  // Each group appears twice (A and H), so we dedupe by name.
  const radios = form.querySelectorAll('input[type="radio"]');

  const seen = new Set();
  const gameNamesInOrder = [];

  for (const r of radios) {
    if (!seen.has(r.name)) {
      seen.add(r.name);
      gameNamesInOrder.push(r.name); // r.name is your GameId
    }
  }

  // For each game (in table order), pick the checked value ("A" or "H")
  let out = "";
  for (const gameId of gameNamesInOrder) {
    const checked = form.querySelector(
      `input[type="radio"][name="${CSS.escape(gameId)}"]:checked`,
    );
    out += checked ? checked.value : "?"; // putting the ? in to flag missing picks.
  }

  if (out.includes("?")) {
    console.log("Missing picks detected.");
    const proceedWithDefaultPicks = window.confirm(
      "You did not make all picks. Missing picks are marked with '?'. Continue and use your default algorithm picks for the missing games?",
    );

    if (!proceedWithDefaultPicks) {
      console.log("User cancelled. Please complete all picks before submitting.");
      return null;
    }

    console.log("Will use selected algorithm picks for missing games.");
    const defaultAlgorithm = "random";
    console.log(`Default algorithm: ${defaultAlgorithm}`);

    switch (defaultAlgorithm) {
      case "home":
        out = out.replace(/\?/g, "H");
        break;
      case "away":
        out = out.replace(/\?/g, "A");
        break;
      case "favorites":
        // Placeholder until favorites logic is wired in.
        out = out.replace(/\?/g, "H");
        break;
      case "underdogs":
        // Placeholder until underdogs logic is wired in.
        out = out.replace(/\?/g, "A");
        break;
      case "random":
      default:
        out = out.replace(/\?/g, () => (Math.random() < 0.5 ? "H" : "A"));
    }
    console.log("Picks after applying default algorithm:", out);
  } else {
    console.log("All picks made.");
  }
  console.log("Picks string:", out);
  return out; // e.g. "HAHA"
}
