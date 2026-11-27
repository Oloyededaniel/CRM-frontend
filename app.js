const FIELDS = ["name", "company", "industry", "email", "address", "status", "notes"];
const EMAIL_PATTERN = /^[A-Za-z0-9](?:[A-Za-z0-9._%+\-']{0,62}[A-Za-z0-9])?@(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$/;
const EMAIL_MESSAGE = "Enter an email such as name@company.com or name@company.co.uk.";

const state = {
  customers: [],
  employees: [],
  editingId: "",
  editingEmployeeId: "",
  query: "",
  city: "",
  mode: "create",
  connections: [],
};

let placeTimer = 0;
let placeTicket = 0;

const listEl = document.querySelector("#list");
const countEl = document.querySelector("#count");
const searchEl = document.querySelector("#search");
const editorEl = document.querySelector("#editor");
const formEl = document.querySelector("#customer-form");
const titleEl = document.querySelector("#editor-title");
const copyEl = document.querySelector("#editor-copy");
const formStatusEl = document.querySelector("#form-status");
const deleteButton = document.querySelector("#delete-button");
const saveButton = document.querySelector("#save-button");
const employeeListEl = document.querySelector("#employee-list");

searchEl.addEventListener("input", () => {
  state.query = searchEl.value.trim().toLowerCase();
  renderList();
});

document.querySelector("#add-button").addEventListener("click", () => openEditor());
document.querySelector("#record-choices").addEventListener("click", (event) => {
  const mode = event.target.closest("button")?.dataset.mode;
  if (!mode) return;
  resetEmployeeForm();
  setStatus("");
  showMode(mode);
  if (mode === "company" || mode === "owner") document.querySelector("#name").focus();
  if (mode === "industry") document.querySelector("#industry").focus();
  if (mode === "add-employee") document.querySelector("#employee-name").focus();
});
document.querySelector("#choice-back").addEventListener("click", () => {
  resetEmployeeForm();
  setStatus("");
  showMode("choose");
});
document.querySelector("#cancel-button").addEventListener("click", closeEditor);
deleteButton.addEventListener("click", removeCustomer);
formEl.addEventListener("submit", (event) => {
  event.preventDefault();
  saveCustomer();
});
document.querySelector("#add-employee").addEventListener("click", addEmployee);
document.querySelector("#cancel-employee").addEventListener("click", () => {
  resetEmployeeForm();
  setStatus("");
});
document.querySelector("#employee-form").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target.tagName !== "SELECT") {
    event.preventDefault();
    addEmployee();
  }
});
document.querySelector("#employee-contact").addEventListener("change", showEmployeeContact);
document.querySelector("#email").addEventListener("input", (event) => {
  renderEmailChecks(document.querySelector("#email-checks"), event.target.value);
});
document.querySelector("#employee-email").addEventListener("input", (event) => {
  renderEmailChecks(document.querySelector("#employee-email-checks"), event.target.value);
});
document.querySelector("#phone").addEventListener("input", (event) => {
  event.target.value = event.target.value.replace(/\D/g, "").slice(0, 15);
});
document.querySelector("#employee-phone").addEventListener("input", (event) => {
  event.target.value = event.target.value.replace(/\D/g, "").slice(0, 15);
});
document.querySelector("#address").addEventListener("input", () => {
  state.city = "";
  const query = fieldValue("address");
  window.clearTimeout(placeTimer);
  if (query.length < 3) {
    closePlaces();
    return;
  }
  placeTimer = window.setTimeout(() => searchPlaces(query), 300);
});
document.querySelector("#address").addEventListener("keydown", (event) => {
  if (event.key === "Escape") closePlaces();
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".place-field")) closePlaces();
});

function fieldValue(key) {
  return document.querySelector(`#${key}`).value.trim();
}

function setField(key, value) {
  document.querySelector(`#${key}`).value = value || "";
}

function payloadFromForm() {
  const phone = document.querySelector("#phone").value.replace(/\D/g, "");
  return {
    ...Object.fromEntries(FIELDS.map((key) => [key, fieldValue(key)])),
    phone,
    countryCode: phone ? document.querySelector("#country-code").value : "",
    city: state.city,
    employees: state.employees,
    share: [...document.querySelectorAll("#share-list input:checked")].map((input) => input.value),
  };
}

function displayPhone(customer) {
  if (!customer.phone) return "";
  const dial = String(customer.countryCode || "").split(":")[1];
  return dial ? `${dial} ${customer.phone}` : customer.phone;
}

function applyPhone(customer) {
  const select = document.querySelector("#country-code");
  const phone = document.querySelector("#phone");
  const stored = customer?.countryCode || "";
  if (stored && [...select.options].some((option) => option.value === stored)) {
    select.value = stored;
    phone.value = String(customer.phone || "").replace(/\D/g, "");
    return;
  }
  const raw = String(customer?.phone || "").replace(/\s/g, "");
  const codes = [...select.options].map((option) => option.value.split(":")[1]).sort((left, right) => right.length - left.length);
  const match = codes.find((code) => raw.startsWith(code));
  if (match) {
    select.value = [...select.options].find((option) => option.value.endsWith(`:${match}`)).value;
    phone.value = raw.slice(match.length).replace(/\D/g, "");
    return;
  }
  select.value = "GB:+44";
  phone.value = raw.replace(/\D/g, "");
}

function emailCriteria(value) {
  const email = value.trim();
  const at = email.indexOf("@");
  const singleAt = at > 0 && at === email.lastIndexOf("@");
  const local = singleAt ? email.slice(0, at) : "";
  const domain = singleAt ? email.slice(at + 1) : "";
  const labels = domain ? domain.split(".") : [];
  const labelOk = (label) => /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(label);
  const domainOk = labels.length >= 2 && labels.every(labelOk);
  const endingOk = domainOk && /^[A-Za-z]{2,}$/.test(labels[labels.length - 1]);
  return [
    { label: "Includes @", met: singleAt },
    { label: "Has a name before @", met: /^[A-Za-z0-9](?:[A-Za-z0-9._%+\-']{0,62}[A-Za-z0-9])?$/.test(local) },
    { label: "Has a domain", met: domainOk },
    { label: "Ends with .com, .co.uk, or another normal ending", met: endingOk },
  ];
}

function renderEmailChecks(list, value) {
  if (!value.trim()) {
    list.hidden = true;
    list.replaceChildren();
    return;
  }
  list.hidden = false;
  list.replaceChildren();
  emailCriteria(value).forEach((check) => {
    const item = document.createElement("li");
    item.className = check.met ? "met" : "";
    const tick = document.createElement("span");
    tick.className = "tick";
    tick.textContent = check.met ? "✓" : "○";
    const text = document.createElement("span");
    text.textContent = check.label;
    item.append(tick, text);
    list.append(item);
  });
}

function contactProblem(body) {
  if (body.email && !EMAIL_PATTERN.test(body.email)) {
    return EMAIL_MESSAGE;
  }
  if (body.phone && !/^[0-9]{6,15}$/.test(body.phone)) {
    return "Phone number must be 6 to 15 digits. Choose the country from the list.";
  }
  return "";
}

function setStatus(message, tone) {
  formStatusEl.textContent = message || "";
  formStatusEl.className = `meta${tone ? ` ${tone}` : ""}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    method: options.method || "GET",
    headers: options.body ? { "Content-Type": "application/json" } : {},
    body: options.body,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "The customer list could not be updated.");
  return data;
}

async function loadCustomers() {
  const data = await api("/api/customers");
  state.customers = data.customers || [];
  renderList();
}

function matches(customer) {
  if (!state.query) return true;
  const people = (customer.employees || []).flatMap((employee) => [employee.name, employee.role, employee.permission, employee.email, employee.phone]);
  const haystack = [customer.name, customer.company, customer.industry, customer.email, customer.phone, customer.address, customer.city, ...people]
    .join(" ")
    .toLowerCase();
  return haystack.includes(state.query);
}

function renderList() {
  const visible = state.customers
    .filter(matches)
    .sort((left, right) => (left.company || "").localeCompare(right.company || "") || left.name.localeCompare(right.name));
  countEl.textContent = state.customers.length
    ? `${visible.length} of ${state.customers.length} shown`
    : "No customers yet";
  listEl.replaceChildren();
  if (!visible.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = state.customers.length
      ? "No customer matches that search."
      : "Add the first customer to start the company list.";
    listEl.append(empty);
    return;
  }
  visible.forEach((customer) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "customer-row";
    if (customer.id === state.editingId) row.classList.add("selected");
    row.addEventListener("click", () => openEditor(customer));

    const person = document.createElement("span");
    person.className = "customer-name";
    const company = document.createElement("strong");
    company.textContent = customer.company || "No company yet";
    const staff = customer.employees || [];
    const detail = document.createElement("small");
    const staffLabel = staff.length === 1 ? "1 employee" : `${staff.length} employees`;
    const sources = Object.keys(customer.sources || {}).map((id) => {
      const known = state.connections.find((item) => item.id === id);
      return known ? known.name : id;
    });
    detail.textContent = [customer.name, customer.industry, staff.length ? staffLabel : "", sources.length ? sources.join(", ") : ""].filter(Boolean).join(" · ");
    person.append(company, detail);

    const contact = document.createElement("span");
    contact.className = "customer-contact";
    contact.textContent = [customer.email, displayPhone(customer)].filter(Boolean).join(" · ") || "No contact details";

    const status = document.createElement("span");
    status.className = `badge ${customer.status.toLowerCase()}`;
    status.textContent = customer.status;

    row.append(person, contact, status);
    listEl.append(row);
  });
}

function showMode(mode) {
  state.mode = mode;
  const saved = Boolean(state.editingId);
  document.querySelector("#record-choices").hidden = mode !== "choose";
  document.querySelector("#choice-back").hidden = mode === "choose" || mode === "create";
  const singleField = mode === "industry" ? "#industry" : mode === "owner" ? "#name" : "";
  document.querySelector("#company-fields").hidden = mode !== "company" && mode !== "create" && mode !== "industry" && mode !== "owner";
  document.querySelectorAll("#company-fields > label").forEach((label) => {
    label.hidden = Boolean(singleField) && !label.querySelector(singleField);
  });
  document.querySelector(".employees").hidden = mode === "choose" || mode === "company" || mode === "industry" || mode === "owner";
  document.querySelector("#employee-form").hidden = mode === "update-employee" && !state.editingEmployeeId;
  saveButton.hidden = mode === "choose" || mode === "add-employee" || mode === "update-employee";
  deleteButton.hidden = !saved || mode === "add-employee" || mode === "update-employee" || mode === "industry" || mode === "owner";
  saveButton.textContent = mode === "company" ? "Save company" : mode === "industry" ? "Save industry" : mode === "owner" ? "Save owner" : "Save customer";
  if (mode === "choose") {
    titleEl.textContent = fieldValue("company") || "No company yet";
    copyEl.textContent = `${fieldValue("name") || "Owner"}. Choose whether to update the owner, the company, its industry, or its employees.`;
  } else if (mode === "company") {
    titleEl.textContent = "Update company information";
    copyEl.textContent = "Change the owner, company, and industry, then save. A linked HubSpot company is updated too.";
  } else if (mode === "owner") {
    titleEl.textContent = "Update owner";
    copyEl.textContent = "Change the owner's name, then save. A linked HubSpot company is updated too.";
  } else if (mode === "industry") {
    titleEl.textContent = "Update industry";
    copyEl.textContent = "Choose the industry, then save. A linked HubSpot company is updated too.";
  } else if (mode === "add-employee") {
    titleEl.textContent = "Add employees";
    copyEl.textContent = "Add a person at this company. Each person is saved immediately.";
  } else if (mode === "update-employee") {
    titleEl.textContent = "Update employees";
    copyEl.textContent = "Edit or remove a person at this company.";
  } else {
    titleEl.textContent = "New customer";
    copyEl.textContent = "Enter the details the company needs to reach this customer.";
  }
  renderEmployees();
  refreshShareFields();
}

function openEditor(customer) {
  state.editingId = customer?.id || "";
  FIELDS.forEach((key) => setField(key, customer?.[key] || (key === "status" ? "Lead" : "")));
  if (!fieldValue("address") && customer?.city) setField("address", customer.city);
  state.city = customer?.city || "";
  closePlaces();
  applyPhone(customer);
  state.employees = (customer?.employees || []).map((employee) => ({ ...employee }));
  resetEmployeeForm();
  renderEmailChecks(document.querySelector("#email-checks"), fieldValue("email"));
  setStatus("");
  editorEl.hidden = false;
  showMode(customer ? "choose" : "create");
  renderList();
  if (!customer) document.querySelector("#name").focus();
}

function closePlaces() {
  window.clearTimeout(placeTimer);
  placeTicket += 1;
  const list = document.querySelector("#place-list");
  list.hidden = true;
  list.replaceChildren();
  document.querySelector("#address").setAttribute("aria-expanded", "false");
}

async function searchPlaces(query) {
  const ticket = ++placeTicket;
  try {
    const data = await api(`/api/places?q=${encodeURIComponent(query)}`);
    if (ticket !== placeTicket || fieldValue("address") !== query) return;
    renderPlaces(data.places || [], data.error || "");
  } catch (error) {
    if (ticket !== placeTicket) return;
    renderPlaces([], "Address suggestions are unavailable. You can still type the address.");
  }
}

function renderPlaces(places, note) {
  const list = document.querySelector("#place-list");
  const input = document.querySelector("#address");
  list.replaceChildren();
  if (!places.length) {
    const item = document.createElement("li");
    item.className = "place-note";
    item.textContent = note || "No matching addresses. You can keep the address you typed.";
    list.append(item);
  } else {
    places.forEach((place) => {
      const item = document.createElement("li");
      const button = document.createElement("button");
      button.type = "button";
      button.className = "place-option";
      button.textContent = place.label;
      button.addEventListener("click", () => {
        input.value = place.label;
        state.city = place.city || "";
        closePlaces();
        input.focus();
      });
      item.append(button);
      list.append(item);
    });
  }
  list.hidden = false;
  input.setAttribute("aria-expanded", "true");
}

function closeEditor() {
  state.editingId = "";
  state.employees = [];
  state.city = "";
  closePlaces();
  editorEl.hidden = true;
  formEl.reset();
  resetEmployeeForm();
  renderEmailChecks(document.querySelector("#email-checks"), "");
  renderEmployees();
  renderList();
}

function showEmployeeContact() {
  const useEmail = document.querySelector("#employee-contact").value === "email";
  document.querySelector("#employee-email-wrap").hidden = !useEmail;
  document.querySelector("#employee-phone-wrap").hidden = useEmail;
}

function resetEmployeeForm() {
  state.editingEmployeeId = "";
  document.querySelector("#employee-name").value = "";
  document.querySelector("#employee-role").value = "Employee Level 1";
  document.querySelector("#employee-permission").value = "Read";
  document.querySelector("#employee-contact").value = "email";
  document.querySelector("#employee-email").value = "";
  document.querySelector("#employee-phone").value = "";
  document.querySelector("#employee-country").value = "GB:+44";
  document.querySelector("#add-employee").textContent = "Add employee";
  document.querySelector("#cancel-employee").hidden = true;
  showEmployeeContact();
  renderEmailChecks(document.querySelector("#employee-email-checks"), "");
  if (state.mode === "update-employee") document.querySelector("#employee-form").hidden = true;
}

function employeeFormStarted() {
  return Boolean(
    document.querySelector("#employee-name").value.trim()
    || document.querySelector("#employee-email").value.trim()
    || document.querySelector("#employee-phone").value.trim()
  );
}

function employeeFromForm() {
  const name = document.querySelector("#employee-name").value.trim();
  const contact = document.querySelector("#employee-contact").value === "phone" ? "phone" : "email";
  if (!name) {
    setStatus("Enter the employee name.", "bad");
    document.querySelector("#employee-name").focus();
    return null;
  }
  const employee = {
    id: state.editingEmployeeId || crypto.randomUUID().replace(/-/g, ""),
    name,
    role: document.querySelector("#employee-role").value,
    permission: document.querySelector("#employee-permission").value,
    contact,
    email: "",
    phone: "",
    countryCode: "",
  };
  if (contact === "email") {
    employee.email = document.querySelector("#employee-email").value.trim();
    if (!EMAIL_PATTERN.test(employee.email)) {
      setStatus(EMAIL_MESSAGE, "bad");
      document.querySelector("#employee-email").focus();
      return null;
    }
  } else {
    employee.phone = document.querySelector("#employee-phone").value.replace(/\D/g, "");
    employee.countryCode = document.querySelector("#employee-country").value;
    if (!/^[0-9]{6,15}$/.test(employee.phone)) {
      setStatus("Phone number must be 6 to 15 digits. Choose the country from the list.", "bad");
      document.querySelector("#employee-phone").focus();
      return null;
    }
  }
  return employee;
}

function renderEmployees() {
  employeeListEl.replaceChildren();
  if (!state.employees.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = state.mode === "update-employee"
      ? "No employees yet. Go back and choose Add employees."
      : "No employees yet.";
    employeeListEl.append(empty);
    return;
  }
  state.employees.forEach((employee) => {
    const row = document.createElement("div");
    row.className = "employee-row";
    const name = document.createElement("strong");
    name.textContent = employee.name;
    const role = document.createElement("span");
    role.textContent = `${employee.role} · ${employee.permission}`;
    const contact = document.createElement("span");
    contact.textContent = employee.contact === "phone" ? displayPhone(employee) : employee.email;
    const actions = document.createElement("div");
    actions.className = "employee-actions";
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "text-button";
    edit.textContent = "Edit";
    edit.addEventListener("click", () => editEmployee(employee));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "text-button danger-text";
    remove.textContent = "Remove";
    remove.addEventListener("click", () => {
      const next = state.employees.filter((item) => item.id !== employee.id);
      commitEmployees(next, "Employee removed.");
    });
    if (state.mode !== "add-employee") {
      actions.append(edit, remove);
      row.append(name, role, contact, actions);
    } else {
      row.append(name, role, contact);
    }
    employeeListEl.append(row);
  });
}

function editEmployee(employee) {
  state.editingEmployeeId = employee.id;
  document.querySelector("#employee-name").value = employee.name || "";
  document.querySelector("#employee-role").value = employee.role || "Employee Level 1";
  document.querySelector("#employee-permission").value = employee.permission || "Read";
  document.querySelector("#employee-contact").value = employee.contact === "phone" ? "phone" : "email";
  document.querySelector("#employee-email").value = employee.email || "";
  document.querySelector("#employee-phone").value = String(employee.phone || "").replace(/\D/g, "");
  const country = document.querySelector("#employee-country");
  country.value = [...country.options].some((option) => option.value === employee.countryCode) ? employee.countryCode : "GB:+44";
  document.querySelector("#employee-form").hidden = false;
  document.querySelector("#add-employee").textContent = "Update employee";
  document.querySelector("#cancel-employee").hidden = false;
  showEmployeeContact();
  renderEmailChecks(document.querySelector("#employee-email-checks"), employee.email || "");
  document.querySelector("#employee-name").focus();
}

async function commitEmployees(nextEmployees, message) {
  const previous = state.employees;
  state.employees = nextEmployees;
  renderEmployees();
  if (!state.editingId) {
    setStatus(`${message} Save the customer to keep this list.`, "ok");
    return true;
  }
  try {
    const data = await api(`/api/customers/${state.editingId}`, {
      method: "PUT",
      body: JSON.stringify(payloadFromForm()),
    });
    state.customers = state.customers.map((item) => (item.id === data.customer.id ? data.customer : item));
    state.employees = (data.customer.employees || []).map((employee) => ({ ...employee }));
    renderEmployees();
    renderList();
    setStatus(message, "ok");
    return true;
  } catch (error) {
    state.employees = previous;
    renderEmployees();
    setStatus(error.message, "bad");
    return false;
  }
}

async function addEmployee() {
  const employee = employeeFromForm();
  if (!employee) return;
  const next = state.editingEmployeeId
    ? state.employees.map((item) => (item.id === employee.id ? employee : item))
    : [...state.employees, employee];
  const message = state.editingEmployeeId ? "Employee updated." : "Employee added.";
  const saved = await commitEmployees(next, message);
  if (saved) {
    resetEmployeeForm();
    document.querySelector("#employee-name").focus();
  }
}

function rememberCustomer(customer, message) {
  const returnToChoices = !state.editingId || state.mode === "company" || state.mode === "industry" || state.mode === "owner";
  if (state.editingId) {
    state.customers = state.customers.map((item) => (item.id === customer.id ? customer : item));
  } else {
    state.customers.push(customer);
    state.editingId = customer.id;
  }
  state.employees = (customer.employees || []).map((employee) => ({ ...employee }));
  renderList();
  if (returnToChoices) showMode("choose");
  else renderEmployees();
  setStatus(message, "ok");
}

async function saveCustomer() {
  if (employeeFormStarted()) {
    const employee = employeeFromForm();
    if (!employee) return;
    state.employees = state.editingEmployeeId
      ? state.employees.map((item) => (item.id === employee.id ? employee : item))
      : [...state.employees, employee];
    resetEmployeeForm();
    renderEmployees();
  }
  const body = payloadFromForm();
  if (!body.name) {
    setStatus("Enter the owner's name.", "bad");
    document.querySelector("#name").focus();
    return;
  }
  const problem = contactProblem(body);
  if (problem) {
    setStatus(problem, "bad");
    document.querySelector(body.email && !EMAIL_PATTERN.test(body.email) ? "#email" : "#phone").focus();
    return;
  }
  saveButton.disabled = true;
  saveButton.textContent = "Saving…";
  try {
    if (state.editingId) {
      const data = await api(`/api/customers/${state.editingId}`, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      const shared = (data.shared || []).filter((item) => item.ok).map((item) => item.name);
      const failed = (data.shared || []).filter((item) => !item.ok);
      const extra = shared.length ? ` Updated in ${shared.join(", ")}.` : "";
      const problem = failed.length ? ` ${failed.map((item) => `${item.name}: ${item.error}`).join(" ")}` : "";
      rememberCustomer(data.customer, `Customer updated.${extra}${problem}`);
    } else {
      const data = await api("/api/customers", { method: "POST", body: JSON.stringify(body) });
      const shared = (data.shared || []).filter((item) => item.ok).map((item) => item.name);
      const failed = (data.shared || []).filter((item) => !item.ok);
      const extra = shared.length ? ` Also created in ${shared.join(", ")}.` : "";
      const problem = failed.length ? ` ${failed.map((item) => `${item.name}: ${item.error}`).join(" ")}` : "";
      rememberCustomer(data.customer, `Customer added.${extra}${problem}`);
    }
  } catch (error) {
    setStatus(error.message, "bad");
  } finally {
    saveButton.disabled = false;
    saveButton.textContent = "Save customer";
  }
}

async function removeCustomer() {
  if (!state.editingId) return;
  const current = state.customers.find((item) => item.id === state.editingId);
  const confirmed = window.confirm(`Remove ${current?.name || "this customer"} from the company list?`);
  if (!confirmed) return;
  deleteButton.disabled = true;
  try {
    await api(`/api/customers/${state.editingId}`, { method: "DELETE" });
    state.customers = state.customers.filter((item) => item.id !== state.editingId);
    closeEditor();
  } catch (error) {
    setStatus(error.message, "bad");
  } finally {
    deleteButton.disabled = false;
  }
}

const authStatus = document.querySelector("#auth-status");
const authTitle = document.querySelector("#auth-title");
const authLede = document.querySelector("#auth-lede");
const authSwitch = document.querySelector("#auth-switch");
const authCard = {
  signIn: document.querySelector("#sign-in-form"),
  create: document.querySelector("#create-form"),
  code: document.querySelector("#code-form"),
  logo: document.querySelector("#logo-form"),
};
let authMode = "signin";
let pendingEmail = "";
let pendingAccount = null;
let logoData = "";
let profileLogoData = "";
let currentAccount = null;
let sendTimer = 0;
let sending = false;
let sentKey = "";

function setAuthStatus(message, tone) {
  authStatus.textContent = message || "";
  authStatus.className = `meta${tone ? ` ${tone}` : ""}`;
}

function showAuth(mode) {
  document.querySelector("#auth").hidden = false;
  document.querySelector("#workspace").hidden = true;
  sessionStorage.removeItem("logoStep");
  sessionStorage.removeItem("activeTab");
  applyBrand(null);
  if (mode) selectAuth(mode);
}

function markTab() {
  sessionStorage.setItem("activeTab", "1");
}

function selectAuth(mode) {
  authMode = mode;
  const creating = mode === "create";
  authTitle.textContent = "Welcome";
  authLede.textContent = "Enter your email. A 6-digit code is sent to that address and stays valid for 15 minutes.";
  authSwitch.hidden = false;
  document.querySelector(".auth-card").classList.remove("otp-mode");
  authCard.signIn.hidden = creating;
  authCard.create.hidden = !creating;
  authCard.code.hidden = true;
  authCard.logo.hidden = true;
  document.querySelector("#show-sign-in").classList.toggle("active", !creating);
  document.querySelector("#show-create").classList.toggle("active", creating);
  document.querySelector("#show-sign-in").setAttribute("aria-selected", String(!creating));
  document.querySelector("#show-create").setAttribute("aria-selected", String(creating));
}

function showCodeStep(email) {
  pendingEmail = email;
  document.querySelector(".auth-card").classList.add("otp-mode");
  authSwitch.hidden = true;
  authCard.signIn.hidden = true;
  authCard.create.hidden = true;
  authCard.logo.hidden = true;
  authCard.code.hidden = false;
  document.querySelector("#code-copy").textContent = `Enter the 6-digit code sent to ${email}. It is valid for 15 minutes.`;
  document.querySelectorAll(".otp-digit").forEach((input) => {
    input.value = "";
  });
  document.querySelector(".otp-digit").focus();
}

function showLogoStep(account) {
  pendingAccount = account;
  markTab();
  sessionStorage.setItem("logoStep", "1");
  document.querySelector("#auth").hidden = false;
  document.querySelector("#workspace").hidden = true;
  authTitle.textContent = "Add company logo";
  authLede.textContent = "This preview is how the logo appears at the top of the home page.";
  authSwitch.hidden = true;
  authCard.signIn.hidden = true;
  authCard.create.hidden = true;
  authCard.code.hidden = true;
  authCard.logo.hidden = false;
  document.querySelector(".auth-card").classList.remove("otp-mode");
  document.querySelector("#preview-name").textContent = account.name || "Company records";
  setAuthStatus("");
}

function enterApp(account, view) {
  currentAccount = account;
  markTab();
  sessionStorage.removeItem("logoStep");
  document.querySelector("#auth").hidden = true;
  document.querySelector("#workspace").hidden = false;
  document.querySelector("#brand-name").textContent = account.name || "Company records";
  const logo = document.querySelector("#brand-logo");
  const mark = document.querySelector("#brand-mark");
  if (account.logo) {
    logo.src = `/api/logo?v=${Date.now()}`;
    logo.alt = `${account.name} logo`;
    logo.hidden = false;
    mark.hidden = true;
  } else {
    logo.hidden = true;
    mark.hidden = false;
    applyBrand(null);
  }
  if (view === "profile") showProfile();
  else showRecords();
  loadCustomers().catch((error) => {
    countEl.textContent = error.message;
    countEl.className = "meta bad";
  });
  loadConnections().catch(() => {});
}

function showRecords() {
  document.querySelector("#profile").hidden = true;
  document.querySelector("#connections").hidden = true;
  document.querySelector("#records").hidden = false;
  restoreBrand();
}

function showProfile() {
  if (!currentAccount) return;
  closeEditor();
  document.querySelector("#records").hidden = true;
  document.querySelector("#connections").hidden = true;
  document.querySelector("#profile").hidden = false;
  document.querySelector("#profile-name").textContent = currentAccount.name || "Company records";
  document.querySelector("#profile-email").textContent = currentAccount.email || "";
  const profileLogo = document.querySelector("#profile-logo");
  const profileMark = document.querySelector("#profile-mark");
  if (currentAccount.logo) {
    setLogoSlot(profileLogo, profileMark, `/api/logo?v=${Date.now()}`);
    profileLogo.alt = `${currentAccount.name} logo`;
  } else {
    setLogoSlot(profileLogo, profileMark, "");
  }
  document.querySelector("#profile-file").value = "";
  profileLogoData = "";
  setProfileStatus("");
}

function setLogoSlot(image, mark, src) {
  const drop = image.closest(".logo-drop");
  if (src) {
    image.src = src;
    image.hidden = false;
    mark.hidden = true;
    if (drop) drop.classList.add("has-logo");
    return;
  }
  image.removeAttribute("src");
  image.hidden = true;
  mark.hidden = false;
  if (drop) drop.classList.remove("has-logo");
}

function setHomePreview(src) {
  const image = document.querySelector("#home-preview-logo");
  const mark = document.querySelector("#home-preview-mark");
  if (src) {
    image.src = src;
    image.hidden = false;
    mark.hidden = true;
    return;
  }
  image.removeAttribute("src");
  image.hidden = true;
  mark.hidden = false;
}

function bindLogoDrop(drop, input) {
  ["dragenter", "dragover"].forEach((name) => {
    drop.addEventListener(name, (event) => {
      event.preventDefault();
      drop.classList.add("is-drag");
    });
  });
  ["dragleave", "drop"].forEach((name) => {
    drop.addEventListener(name, (event) => {
      event.preventDefault();
      if (name === "dragleave") drop.classList.remove("is-drag");
    });
  });
  drop.addEventListener("drop", (event) => {
    drop.classList.remove("is-drag");
    const files = event.dataTransfer && event.dataTransfer.files;
    if (!files || !files.length) return;
    input.files = files;
    input.dispatchEvent(new Event("change"));
  });
}

function setProfileStatus(message, tone) {
  const status = document.querySelector("#profile-status");
  status.textContent = message || "";
  status.className = `meta${tone ? ` ${tone}` : ""}`;
}

function restoreBrand() {
  const logo = document.querySelector("#brand-logo");
  if (!logo.hidden && logo.complete && logo.naturalWidth) paintBrand(logo);
  else if (logo.hidden) applyBrand(null);
}

function readLogoFile(file) {
  return new Promise((resolve, reject) => {
    if (!file) {
      resolve("");
      return;
    }
    if (!["image/png", "image/jpeg", "image/webp", "image/gif"].includes(file.type) || file.size > 1_500_000) {
      reject(new Error("Use a PNG, JPEG, WEBP, or GIF logo under 1.5 MB."));
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("The logo file could not be read."));
    reader.readAsDataURL(file);
  });
}

document.querySelector("#show-sign-in").addEventListener("click", () => {
  setAuthStatus("");
  selectAuth("signin");
});
document.querySelector("#show-create").addEventListener("click", () => {
  setAuthStatus("");
  selectAuth("create");
});
document.querySelector("#create-email").addEventListener("input", (event) => {
  renderEmailChecks(document.querySelector("#create-email-checks"), event.target.value);
  queueCodeSend();
});
["#sign-email", "#sign-password", "#create-name", "#create-password", "#create-confirm"].forEach((selector) => {
  document.querySelector(selector).addEventListener("input", queueCodeSend);
});
document.querySelector("#sign-email").addEventListener("blur", () => sendCode({ automatic: true }));
document.querySelector("#create-email").addEventListener("blur", () => sendCode({ automatic: true }));

function currentEmail() {
  const field = authMode === "create" ? "#create-email" : "#sign-email";
  return document.querySelector(field).value.trim();
}

function authProblem() {
  if (authMode === "create") {
    const name = document.querySelector("#create-name").value.trim();
    const email = document.querySelector("#create-email").value.trim();
    const password = document.querySelector("#create-password").value;
    const confirm = document.querySelector("#create-confirm").value;
    if (!name) return "Enter your name.";
    if (!EMAIL_PATTERN.test(email)) return EMAIL_MESSAGE;
    if (password.length < 8) return "Use a password of at least 8 characters.";
    if (password !== confirm) return "The passwords do not match.";
    return "";
  }
  const email = document.querySelector("#sign-email").value.trim();
  const password = document.querySelector("#sign-password").value;
  if (!EMAIL_PATTERN.test(email)) return EMAIL_MESSAGE;
  if (!password) return "Enter your password.";
  return "";
}

function queueCodeSend() {
  window.clearTimeout(sendTimer);
  if (sending || !document.querySelector("#code-form").hidden) return;
  sendTimer = window.setTimeout(() => sendCode({ automatic: true }), 800);
}

async function sendCode({ automatic } = {}) {
  if (sending) return;
  const problem = authProblem();
  if (problem) {
    if (!automatic) setAuthStatus(problem, "bad");
    return;
  }
  const email = currentEmail();
  const key = `${authMode}:${email.toLowerCase()}`;
  if (automatic && sentKey === key) return;
  sending = true;
  sentKey = key;
  showCodeStep(email);
  try {
    const data = authMode === "create"
      ? await api("/api/auth/sign-up", {
        method: "POST",
        body: JSON.stringify({
          name: document.querySelector("#create-name").value.trim(),
          email,
          password: document.querySelector("#create-password").value,
          confirm: document.querySelector("#create-confirm").value,
        }),
      })
      : await api("/api/auth/sign-in", {
        method: "POST",
        body: JSON.stringify({
          email,
          password: document.querySelector("#sign-password").value,
        }),
      });
    setAuthStatus("");
  } catch (error) {
    sentKey = "";
    setAuthStatus(error.message, "bad");
  } finally {
    sending = false;
  }
}
document.querySelector("#create-logo").addEventListener("change", () => {
  const file = document.querySelector("#create-logo").files[0];
  const preview = document.querySelector("#preview-logo");
  const mark = document.querySelector("#preview-mark");
  logoData = "";
  if (!file) {
    setLogoSlot(preview, mark, "");
    setHomePreview("");
    applyBrand(null);
    return;
  }
  readLogoFile(file).then((value) => {
    logoData = value;
    setLogoSlot(preview, mark, logoData);
    setHomePreview(logoData);
    setAuthStatus("");
  }).catch((error) => {
    document.querySelector("#create-logo").value = "";
    setLogoSlot(preview, mark, "");
    setHomePreview("");
    applyBrand(null);
    setAuthStatus(error.message, "bad");
  });
});
function otpDigits() {
  return [...document.querySelectorAll(".otp-digit")];
}

function otpValue() {
  return otpDigits().map((input) => input.value).join("");
}

document.querySelector("#otp-boxes").addEventListener("input", (event) => {
  const input = event.target;
  if (!input.classList.contains("otp-digit")) return;
  const boxes = otpDigits();
  const start = boxes.indexOf(input);
  const digits = input.value.replace(/\D/g, "");
  if (!digits) {
    input.value = "";
    return;
  }
  digits.slice(0, boxes.length - start).split("").forEach((digit, index) => {
    boxes[start + index].value = digit;
  });
  const next = Math.min(start + digits.length, boxes.length - 1);
  boxes[next].focus();
});

document.querySelector("#otp-boxes").addEventListener("keydown", (event) => {
  const input = event.target;
  if (!input.classList.contains("otp-digit") || event.key !== "Backspace" || input.value) return;
  const boxes = otpDigits();
  const index = boxes.indexOf(input);
  if (index > 0) {
    boxes[index - 1].value = "";
    boxes[index - 1].focus();
  }
});

document.querySelector("#otp-boxes").addEventListener("paste", (event) => {
  const text = (event.clipboardData || window.clipboardData).getData("text").replace(/\D/g, "").slice(0, 6);
  if (!text) return;
  event.preventDefault();
  const boxes = otpDigits();
  text.split("").forEach((digit, index) => {
    boxes[index].value = digit;
  });
  boxes[Math.min(text.length, boxes.length) - 1].focus();
});

document.querySelector("#sign-in-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendCode();
});

document.querySelector("#create-form").addEventListener("submit", (event) => {
  event.preventDefault();
  sendCode();
});

document.querySelector("#code-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#code-button");
  button.disabled = true;
  setAuthStatus("");
  try {
    const data = await api(authMode === "create" ? "/api/auth/verify" : "/api/auth/confirm", {
      method: "POST",
      body: JSON.stringify({
        email: pendingEmail,
        code: otpValue(),
      }),
    });
    document.querySelector("#sign-password").value = "";
    document.querySelector("#create-password").value = "";
    document.querySelector("#create-confirm").value = "";
    if (authMode === "create") showLogoStep(data.account);
    else enterApp(data.account);
  } catch (error) {
    setAuthStatus(error.message, "bad");
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#code-resend").addEventListener("click", async () => {
  if (sending) return;
  sending = true;
  setAuthStatus("");
  showCodeStep(pendingEmail);
  try {
    const data = authMode === "create"
      ? await api("/api/auth/sign-up", {
        method: "POST",
        body: JSON.stringify({
          name: document.querySelector("#create-name").value.trim(),
          email: pendingEmail,
          password: document.querySelector("#create-password").value,
          confirm: document.querySelector("#create-confirm").value,
        }),
      })
      : await api("/api/auth/sign-in", {
        method: "POST",
        body: JSON.stringify({
          email: pendingEmail,
          password: document.querySelector("#sign-password").value,
        }),
      });
    showCodeStep(data.email);
    setAuthStatus("A new code has been sent.", "ok");
  } catch (error) {
    showCodeStep(pendingEmail);
    setAuthStatus(error.message, "bad");
  } finally {
    sending = false;
  }
});

document.querySelector("#code-back").addEventListener("click", () => {
  setAuthStatus("");
  sentKey = "";
  authCard.code.hidden = true;
  selectAuth(authMode === "create" ? "create" : "signin");
});

document.querySelector("#logo-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#logo-button");
  button.disabled = true;
  setAuthStatus("");
  try {
    let account = pendingAccount;
    if (logoData) {
      const data = await api("/api/logo", {
        method: "POST",
        body: JSON.stringify({ logo: logoData }),
      });
      account = data.account;
    }
    enterApp(account, "profile");
  } catch (error) {
    setAuthStatus(error.message, "bad");
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#sign-out").addEventListener("click", async () => {
  try {
    await api("/api/auth/sign-out", { method: "POST", body: "{}" });
  } catch (error) {
    // The screen still returns to sign-in.
  }
  state.customers = [];
  state.editingId = "";
  closeEditor();
  pendingAccount = null;
  logoData = "";
  profileLogoData = "";
  currentAccount = null;
  showAuth("signin");
  setAuthStatus("Signed out.", "ok");
});

function channel(value) {
  const scaled = value / 255;
  return scaled <= 0.03928 ? scaled / 12.92 : ((scaled + 0.055) / 1.055) ** 2.4;
}

function luminance(rgb) {
  return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
}

function mix(from, to, amount) {
  return from.map((value, index) => Math.round(value + (to[index] - value) * amount));
}

function darkenUntil(rgb, limit) {
  let current = rgb.slice();
  for (let step = 0; step < 12 && luminance(current) > limit; step += 1) {
    current = current.map((value) => Math.round(value * 0.84));
  }
  return current;
}

function hex(rgb) {
  return `#${rgb.map((value) => value.toString(16).padStart(2, "0")).join("")}`;
}

function colorDistance(left, right) {
  const red = left[0] - right[0];
  const green = left[1] - right[1];
  const blue = left[2] - right[2];
  return Math.sqrt(red * red + green * green + blue * blue);
}

function brandPalette(image) {
  const canvas = document.createElement("canvas");
  const size = 48;
  canvas.width = size;
  canvas.height = size;
  const context = canvas.getContext("2d", { willReadFrequently: true });
  context.drawImage(image, 0, 0, size, size);
  const pixels = context.getImageData(0, 0, size, size).data;
  const buckets = new Map();
  for (let index = 0; index < pixels.length; index += 4) {
    if (pixels[index + 3] < 160) continue;
    const rgb = [pixels[index], pixels[index + 1], pixels[index + 2]];
    const max = Math.max(...rgb);
    const min = Math.min(...rgb);
    if (max > 246 && min > 236) continue;
    const key = rgb.map((value) => value >> 4).join("-");
    const bucket = buckets.get(key) || { rgb: [0, 0, 0], count: 0, saturation: 0 };
    bucket.rgb = bucket.rgb.map((value, channelIndex) => value + rgb[channelIndex]);
    bucket.count += 1;
    bucket.saturation += max === 0 ? 0 : (max - min) / max;
    buckets.set(key, bucket);
  }
  const ranked = [];
  let total = 0;
  buckets.forEach((bucket) => {
    const saturation = bucket.saturation / bucket.count;
    ranked.push({
      rgb: bucket.rgb.map((value) => Math.round(value / bucket.count)),
      count: bucket.count,
      saturation,
      score: bucket.count * (0.15 + saturation),
    });
    total += bucket.count;
  });
  ranked.sort((left, right) => right.score - left.score);
  const picked = [];
  ranked.forEach((color) => {
    if (picked.length === 3 || !total) return;
    const share = color.count / total;
    if (share < 0.035 && color.saturation < 0.4) return;
    if (picked.some((item) => colorDistance(item.rgb, color.rgb) < 48)) return;
    picked.push(color);
  });
  if (!picked.length) return null;
  const colorful = picked.filter((color) => color.saturation >= 0.22);
  const ordered = colorful.length ? colorful.concat(picked.filter((color) => color.saturation < 0.22)) : picked;
  return ordered.slice(0, 3).map((color) => color.rgb);
}

function applyBrand(palette) {
  const root = document.documentElement;
  ["--bg", "--line", "--teal", "--teal-dark", "--teal-soft", "--on-teal", "--shadow"].forEach((name) => {
    root.style.removeProperty(name);
  });
  if (!palette || !palette.length) return;
  const [first, second, third] = palette;
  const accent = first.slice();
  const deep = darkenUntil(second || accent, 0.18);
  const onAccent = 1.05 / (luminance(accent) + 0.05) >= 4.5 ? "#ffffff" : "#142033";
  let wash = mix([232, 237, 242], first, luminance(first) < 0.08 ? 0.06 : 0.12);
  if (second) wash = mix(wash, second, 0.1);
  if (third) wash = mix(wash, third, 0.08);
  const line = mix([213, 221, 230], second || first, 0.28);
  const soft = mix([255, 255, 255], second || third || first, 0.16);
  root.style.setProperty("--teal", hex(accent));
  root.style.setProperty("--on-teal", onAccent);
  root.style.setProperty("--teal-dark", hex(deep));
  root.style.setProperty("--teal-soft", hex(soft));
  root.style.setProperty("--bg", hex(wash));
  root.style.setProperty("--line", hex(line));
  root.style.setProperty("--shadow", `0 1px 2px rgba(${deep.join(", ")}, 0.05), 0 14px 34px rgba(${deep.join(", ")}, 0.08)`);
}

function paintBrand(image) {
  if (image.hidden || !image.naturalWidth) return;
  applyBrand(brandPalette(image));
}

document.querySelector("#open-profile").addEventListener("click", () => showProfile());
document.querySelector("#open-connections").addEventListener("click", () => showConnections());
document.querySelector("#connections-back").addEventListener("click", () => showRecords());
document.querySelector("#profile-back").addEventListener("click", () => showRecords());
document.querySelector("#profile-file").addEventListener("change", () => {
  const file = document.querySelector("#profile-file").files[0];
  const preview = document.querySelector("#profile-logo");
  const mark = document.querySelector("#profile-mark");
  profileLogoData = "";
  if (!file) return;
  readLogoFile(file).then((value) => {
    profileLogoData = value;
    setLogoSlot(preview, mark, value);
    setProfileStatus("");
  }).catch((error) => {
    document.querySelector("#profile-file").value = "";
    setProfileStatus(error.message, "bad");
  });
});
document.querySelector("#profile-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = document.querySelector("#profile-save");
  if (!profileLogoData) {
    setProfileStatus("Choose a PNG, JPEG, WEBP, or GIF logo under 1.5 MB.", "bad");
    return;
  }
  button.disabled = true;
  setProfileStatus("");
  try {
    const data = await api("/api/logo", {
      method: "POST",
      body: JSON.stringify({ logo: profileLogoData }),
    });
    currentAccount = data.account;
    const logo = document.querySelector("#brand-logo");
    logo.src = `/api/logo?v=${Date.now()}`;
    logo.alt = `${currentAccount.name} logo`;
    logo.hidden = false;
    document.querySelector("#brand-mark").hidden = true;
    setLogoSlot(document.querySelector("#profile-logo"), document.querySelector("#profile-mark"), logo.src);
    document.querySelector("#profile-file").value = "";
    profileLogoData = "";
    setProfileStatus("Logo updated.", "ok");
  } catch (error) {
    setProfileStatus(error.message, "bad");
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#preview-logo").addEventListener("load", (event) => paintBrand(event.currentTarget));
document.querySelector("#brand-logo").addEventListener("load", (event) => paintBrand(event.currentTarget));
document.querySelector("#profile-logo").addEventListener("load", (event) => paintBrand(event.currentTarget));
bindLogoDrop(document.querySelector("#create-drop"), document.querySelector("#create-logo"));
bindLogoDrop(document.querySelector("#profile-drop"), document.querySelector("#profile-file"));

function refreshShareFields() {
  const box = document.querySelector("#share-with");
  const list = document.querySelector("#share-list");
  const ready = state.connections.filter((item) => item.ready);
  box.hidden = Boolean(state.editingId) || state.mode !== "create" || !ready.length;
  list.replaceChildren();
  ready.forEach((platform) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = platform.id;
    label.append(input, document.createTextNode(platform.name));
    list.append(label);
  });
}

function setConnectionStatus(message, tone) {
  const status = document.querySelector("#connections-status");
  status.textContent = message || "";
  status.className = `meta${tone ? ` ${tone}` : ""}`;
}

async function loadConnections() {
  const data = await api("/api/connections");
  state.connections = data.platforms || [];
  renderConnections();
  refreshShareFields();
}

function renderConnections() {
  const list = document.querySelector("#connection-list");
  list.replaceChildren();
  state.connections.forEach((platform) => {
    const card = document.createElement("form");
    card.className = "connect-card";
    const heading = document.createElement("h3");
    heading.textContent = platform.name;
    const detail = document.createElement("p");
    detail.textContent = platform.detail;
    const fields = document.createElement("div");
    fields.className = "connect-fields";
    platform.fields.forEach((field) => {
      const label = document.createElement("label");
      label.className = "stack";
      const span = document.createElement("span");
      span.textContent = field.optional ? `${field.label} (optional)` : field.label;
      const input = document.createElement("input");
      input.name = field.key;
      input.type = field.secret ? "password" : "text";
      input.autocomplete = "off";
      input.maxLength = 500;
      if (field.secret) input.placeholder = platform.secrets[field.key] ? "Saved — leave blank to keep it" : "";
      else input.value = platform.values[field.key] || "";
      label.append(span, input);
      fields.append(label);
    });
    const actions = document.createElement("div");
    actions.className = "connect-actions";
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "primary";
    save.textContent = platform.ready ? "Update" : "Save";
    const importButton = document.createElement("button");
    importButton.type = "button";
    importButton.className = "ghost";
    importButton.textContent = "Import customers";
    importButton.disabled = !platform.ready;
    const status = document.createElement("p");
    status.className = "meta";
    actions.append(save, importButton);
    card.append(heading, detail, fields, actions, status);
    card.addEventListener("submit", async (event) => {
      event.preventDefault();
      save.disabled = true;
      status.textContent = "";
      status.className = "meta";
      const values = {};
      fields.querySelectorAll("input").forEach((input) => {
        values[input.name] = input.value.trim();
      });
      try {
        const data = await api("/api/connections", {
          method: "POST",
          body: JSON.stringify({ id: platform.id, values }),
        });
        const index = state.connections.findIndex((item) => item.id === platform.id);
        state.connections[index] = data.platform;
        renderConnections();
        refreshShareFields();
        setConnectionStatus(`${data.platform.name} saved.`, "ok");
      } catch (error) {
        status.textContent = error.message;
        status.className = "meta bad";
        save.disabled = false;
      }
    });
    importButton.addEventListener("click", async () => {
      importButton.disabled = true;
      status.textContent = "Importing customers…";
      status.className = "meta";
      try {
        const data = await api("/api/connections/import", {
          method: "POST",
          body: JSON.stringify({ id: platform.id }),
        });
        state.customers = data.customers || [];
        renderList();
        status.textContent = `Imported ${data.imported}. Updated ${data.updated}.`;
        status.className = "meta ok";
      } catch (error) {
        status.textContent = error.message;
        status.className = "meta bad";
      } finally {
        importButton.disabled = !platform.ready;
      }
    });
    list.append(card);
  });
}

async function showConnections() {
  closeEditor();
  document.querySelector("#records").hidden = true;
  document.querySelector("#profile").hidden = true;
  document.querySelector("#connections").hidden = false;
  setConnectionStatus("");
  try {
    await loadConnections();
  } catch (error) {
    setConnectionStatus(error.message, "bad");
  }
}

async function boot() {
  if (sessionStorage.getItem("activeTab") !== "1") {
    try {
      await api("/api/auth/sign-out", { method: "POST", body: "{}" });
    } catch (error) {
      // No session was open.
    }
    showAuth("signin");
    return;
  }
  try {
    const data = await api("/api/auth/session");
    if (sessionStorage.getItem("logoStep") === "1") showLogoStep(data.account);
    else enterApp(data.account);
  } catch (error) {
    showAuth("signin");
  }
}

boot();
