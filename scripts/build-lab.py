#!/usr/bin/env python3
"""
build-lab.py — Generate lab.qmd from _data/lab.yml.

Run after editing lab data (or via the cv_admin Flask app's Rebuild button).
"""
from __future__ import annotations
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("pip install pyyaml")

REPO = Path(__file__).resolve().parents[1]
LAB_YAML = REPO / "_data" / "lab.yml"
LAB_QMD = REPO / "lab.qmd"


def html_escape(s):
    if s is None:
        return ""
    return (str(s)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;"))


def render_member(m):
    name = m.get("name", "")
    headshot = m.get("headshot", "")
    bio = m.get("bio", "")
    out = ['::: {.grid}', '::: {.g-col-md-2 .g-col-12}']
    if headshot:
        out.append(f'![]({headshot}){{.headshot fig-alt="{name}"}}')
    else:
        out.append(f'<!-- no headshot for {name} -->')
    out.append(':::')
    out.append('::: {.g-col-md-10 .g-col-12}')
    out.append(f'**{name}** {bio}')
    out.append(':::')
    out.append(':::\n')
    return "\n".join(out)


def main():
    lab = yaml.safe_load(LAB_YAML.read_text(encoding="utf-8"))

    parts = []
    parts.append("---")
    parts.append('title: "DemoTIP Laboratory"')
    parts.append('subtitle: "Democracy, Transparency, Information Provision, and Participation"')
    parts.append("---")
    parts.append("")
    parts.append("::: {.column-page}")
    parts.append("![Lab presentation](images/lab-presentation.jpeg){fig-alt=\"DemoTIP lab members presenting research\"}")
    parts.append(":::")
    parts.append("")
    parts.append("Bringing together researchers interested in transparency, information provision, and participation (TIP), the DemoTIP laboratory applies state of the art research methods to bring answers to empirical problems in political science. Lab members test and challenge conventional theories regarding political transparency and accountability, the provision of political information, and citizen participation in democratic processes. Email if you are interested in getting involved!")
    parts.append("")

    # PI
    pi = lab.get("pi") or {}
    if pi:
        parts.append("## Principal Investigator")
        parts.append("")
        parts.append(render_member(pi))

    # Current grad
    if lab.get("current_grad"):
        parts.append("## McGill Graduate & Post-Doc Researchers")
        parts.append("")
        for m in lab["current_grad"]:
            parts.append(render_member(m))

    # Current undergrad
    if lab.get("current_undergrad"):
        parts.append("## McGill Undergraduate Researchers")
        parts.append("")
        for m in lab["current_undergrad"]:
            parts.append(render_member(m))

    # Alumni
    if lab.get("alumni"):
        parts.append("## DemoTIP Alumni")
        parts.append("")
        parts.append("These students worked with me closely. The research and publications listed are just those completed with me during their time affiliated with the lab. For prospective students, this table gives you a good sense of the types of students who work with me.")
        parts.append("")
        parts.append('<details class="lab-details" open>')
        parts.append('<summary>Show / hide alumni table (click any column to sort)</summary>')
        parts.append("")
        parts.append('<table class="sortable" id="alumni-table">')
        parts.append('<thead><tr>')
        parts.append('<th data-sort-method="string">Researcher</th>')
        parts.append('<th data-sort-method="string">Degree</th>')
        parts.append('<th data-sort-method="number">Graduation Year</th>')
        parts.append('<th data-sort-method="string">Publications &amp; Research</th>')
        parts.append('<th data-sort-method="string">Post-McGill Employment / Education</th>')
        parts.append('</tr></thead>')
        parts.append('<tbody>')
        for a in lab["alumni"]:
            parts.append(
                f'<tr><td><strong>{html_escape(a.get("name",""))}</strong></td>'
                f'<td>{html_escape(a.get("degree",""))}</td>'
                f'<td>{html_escape(str(a.get("graduation_year","") or ""))}</td>'
                f'<td>{a.get("publications","") or ""}</td>'
                f'<td>{a.get("post_mcgill","") or ""}</td></tr>'
            )
        parts.append('</tbody>')
        parts.append('</table>')
        parts.append('</details>')
        parts.append("")
        # Inline sortable JS (kept as-is)
        parts.append("""<script>
(function () {
  function sortTable(table, colIndex, asc, type) {
    var tbody = table.tBodies[0];
    var rows = Array.prototype.slice.call(tbody.rows);
    rows.sort(function (a, b) {
      var ax = a.cells[colIndex].textContent.trim();
      var bx = b.cells[colIndex].textContent.trim();
      if (type === "number") {
        var an = parseFloat(ax); var bn = parseFloat(bx);
        if (isNaN(an)) an = asc ? Infinity : -Infinity;
        if (isNaN(bn)) bn = asc ? Infinity : -Infinity;
        return asc ? an - bn : bn - an;
      }
      return asc
        ? ax.localeCompare(bx, undefined, { sensitivity: "base" })
        : bx.localeCompare(ax, undefined, { sensitivity: "base" });
    });
    rows.forEach(function (r) { tbody.appendChild(r); });
  }
  document.querySelectorAll("table.sortable").forEach(function (table) {
    var headers = table.tHead ? table.tHead.rows[0].cells : [];
    Array.prototype.forEach.call(headers, function (th, idx) {
      var type = th.getAttribute("data-sort-method") || "string";
      var asc = true;
      th.addEventListener("click", function () {
        Array.prototype.forEach.call(headers, function (o) {
          if (o !== th) o.classList.remove("sort-asc", "sort-desc");
        });
        sortTable(table, idx, asc, type);
        th.classList.toggle("sort-asc", asc);
        th.classList.toggle("sort-desc", !asc);
        asc = !asc;
      });
    });
  });
})();
</script>""")

    LAB_QMD.write_text("\n".join(parts), encoding="utf-8")
    print(f"  Wrote {LAB_QMD}", file=sys.stderr)
    print(f"  PI: {1 if lab.get('pi') else 0}", file=sys.stderr)
    print(f"  Grad: {len(lab.get('current_grad', []))}", file=sys.stderr)
    print(f"  Undergrad: {len(lab.get('current_undergrad', []))}", file=sys.stderr)
    print(f"  Alumni: {len(lab.get('alumni', []))}", file=sys.stderr)


if __name__ == "__main__":
    main()
