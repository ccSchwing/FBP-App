import { wireHamburger } from "./uiUtils.js";
import { auth } from "/js/auth.js";

const adminLinks = `
  <li><a href="/fbp-home.html"> -- FBP Home</a></li>
  <li><a href="/fbp-admin/admin.html"> -- Admin Home</a></li>
  <li><a href="/fbp-admin/signup.html"> -- Create FBP Account</a></li>
  <li><a href="/fbp-admin/manageuserprofiles.html"> -- Manage User Profiles</a></li>
  <li><a href="/fbp-admin/setpoolstatus.html" title="Open will increment the week and set pool_open to true.  Close will set pool_open to false, and will make all missing user picks."> -- Open (Tuesday) or Close (Thursday) Pool</a></li>
  <li><a href="/fbp-admin/calculateweeklyresults.html" title="Will calculate weekly game and user results on Tuesday."> -- Tuesday - Mandatory! Calculate Weekly Game and User Results</a></li>
  <li><a href="/getpicksheet.html"> -- Show Pick Sheet</a></li>
  <li><a href="/getgridsheet.html"> -- Show Grid Sheet</a></li>
  <li><a href="/fbp-admin/dashboard.html"> -- Admin Dashboard</a></li>
  <li><a href="/auth-health.html"> -- OIDC Auth Health Check</a></li>
`;

export async function initAdminNav() {
  const isAdmin = await auth.isAdmin();
  if (!isAdmin) {
    const { getServiceUrl } = await import("./urlConfig.js");
    location.href = await getServiceUrl("homePage");
    return;
  }

  // Inject mobile nav into header
  const header = document.querySelector("header");
  if (header) {
    const btn = document.createElement("button");
    btn.id = "menuBtn";
    btn.className = "menu-btn";
    btn.setAttribute("aria-controls", "main-nav");
    btn.setAttribute("aria-expanded", "false");
    btn.innerHTML = '<span></span><span></span><span></span>';
    header.appendChild(btn);

    const nav = document.createElement("nav");
    nav.id = "main-nav";
    nav.setAttribute("aria-label", "Main navigation");
    nav.setAttribute("data-open", "false");
    nav.innerHTML = `<ul>${adminLinks}</ul>`;
    header.appendChild(nav);
  }

  // Inject desktop nav into aside
  const aside = document.querySelector("aside.nav-choices");
  if (aside) {
    aside.innerHTML = `
      <nav aria-label="Main navigation">
        <ul>${adminLinks}</ul>
      </nav>
    `;
  }

  wireHamburger({
    buttonId: "menuBtn",
    navId: "main-nav",
    closeOnLinkClick: true,
  });
}
