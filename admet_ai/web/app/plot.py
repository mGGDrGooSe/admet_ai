"""Defines functions for plotting for the ADMET-AI website."""
import re
from io import BytesIO

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns
from rdkit import Chem
from rdkit.Chem.Draw.rdMolDraw2D import MolDraw2DSVG

from admet_ai.web.app.admet_info import get_admet_name_to_id
from admet_ai.web.app.drugbank import get_drugbank


SVG_WIDTH_PATTERN = re.compile(r"width=['\"]\d+(\.\d+)?[a-z]+['\"]")
SVG_HEIGHT_PATTERN = re.compile(r"height=['\"]\d+(\.\d+)?[a-z]+['\"]")


def replace_svg_dimensions(svg_content: str) -> str:
    """Replace the SVG width and height with 100%.

    :param svg_content: The SVG content.
    :return: The SVG content with the width and height replaced with 100%.
    """
    # Replacing the width and height with 100%
    svg_content = SVG_WIDTH_PATTERN.sub('width="100%"', svg_content)
    svg_content = SVG_HEIGHT_PATTERN.sub('height="100%"', svg_content)

    return svg_content


def plot_drugbank_reference(
    preds_df: pd.DataFrame,
    x_property_name: str | None = None,
    y_property_name: str | None = None,
    atc_code: str | None = None,
) -> str:
    """Creates a 2D scatter plot of the DrugBank reference set vs the new set of molecules on two properties.

    :param preds_df: A DataFrame containing the predictions on the new molecules.
    :param x_property_name: The name of the property to plot on the x-axis.
    :param y_property_name: The name of the property to plot on the y-axis.
    :param atc_code: The ATC code to filter the DrugBank reference set by.
    :return: A string containing the SVG of the plot.
    """
    # Set default values
    if x_property_name is None:
        x_property_name = "Human Intestinal Absorption"

    if y_property_name is None:
        y_property_name = "Clinical Toxicity"

    if atc_code is None:
        atc_code = "all"

    # Get DrugBank reference, optionally filtered ATC code
    drugbank = get_drugbank(atc_code=atc_code)

    # Map property names to IDs
    admet_name_to_id = get_admet_name_to_id()
    x_property_id = admet_name_to_id[x_property_name]
    y_property_id = admet_name_to_id[y_property_name]

    # Scatter plot of DrugBank molecules with density coloring
    sns.scatterplot(
        x=drugbank[x_property_id],
        y=drugbank[y_property_id],
        edgecolor=None,
        label="DrugBank Approved" + (" (ATC filter)" if atc_code != "all" else ""),
    )

    # Set input label
    input_label = "Input Molecule" + ("s" if len(preds_df) > 1 else "")

    # Scatter plot of new molecules
    if len(preds_df) > 0:
        sns.scatterplot(
            x=preds_df[x_property_id],
            y=preds_df[y_property_id],
            color="red",
            marker="*",
            s=200,
            label=input_label,
        )

    # Set title
    plt.title(
        f"{input_label} vs DrugBank Approved"
        + (f"\nATC = {atc_code}" if atc_code != "all" else "")
    )

    # Set axis labels
    plt.xlabel(x_property_name)
    plt.ylabel(y_property_name)

    # Save plot as svg to pass to frontend
    buf = BytesIO()
    plt.savefig(buf, format="svg", bbox_inches="tight")
    plt.close()
    buf.seek(0)
    drugbank_svg = buf.getvalue().decode("utf-8")

    # Set the SVG width and height to 100%
    drugbank_svg = replace_svg_dimensions(drugbank_svg)

    return drugbank_svg


def plot_radial_summary(
    property_name_to_percentile: dict[str, float], property_names: list[str], percentile_suffix: str = ''
) -> str:
    """Creates a radial plot summary of important properties of a molecule in terms of DrugBank approved percentiles.

    :param property_name_to_percentile: A dictionary mapping property names to their DrugBank approved percentiles.
                                        Property names include the percentile_suffix.
    :param property_names: A list of property names to plot (without the percentile_suffix).
    :param percentile_suffix: The suffix to add to the property names to get the DrugBank approved percentiles.
    :return: A string containing the SVG of the plot.
    """
    # Get the percentiles for the properties
    admet_name_to_id = get_admet_name_to_id()
    percentiles = [
        property_name_to_percentile[
            f"{admet_name_to_id[property_name]}_{percentile_suffix}"
        ]
        for property_name in property_names
    ]

    # Calculate the angles of the plot
    angles = np.linspace(0, 2 * np.pi, len(property_names), endpoint=False).tolist()

    # Complete the loop
    percentiles += percentiles[:1]
    angles += angles[:1]

    # Step 3: Create a plot
    fig, ax = plt.subplots(figsize=(4, 4), subplot_kw=dict(polar=True))

    # Plot the data
    ax.fill(angles, percentiles, color="red", alpha=0.25)
    ax.plot(angles, percentiles, color="red", linewidth=2)

    # Set y limits
    ax.set_ylim(0, 100)

    # Labels for radial lines
    yticks = [0, 25, 50, 75, 100]
    yticklabels = [str(ytick) for ytick in yticks]
    ax.set_yticks(yticks)
    ax.set_yticklabels(yticklabels)

    # Labels for categories
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(property_names)

    # Make the plot square (to match square molecule images)
    ax.set_aspect("equal", "box")

    # Ensure no text labels are cut off
    plt.tight_layout()

    # Save plot as svg to pass to frontend
    buf = BytesIO()
    plt.savefig(buf, format="svg")
    plt.close()
    buf.seek(0)
    radial_svg = buf.getvalue().decode("utf-8")

    # Set the SVG width and height to 100%
    radial_svg = replace_svg_dimensions(radial_svg)

    return radial_svg


def plot_molecule_svg(mol: str | Chem.Mol) -> str:
    """Plots a molecule as an SVG image.

    :param mol: A SMILES string or RDKit molecule.
    :return: An SVG image of the molecule.
    """
    # Convert SMILES to Mol if needed
    if isinstance(mol, str):
        mol = Chem.MolFromSmiles(mol)

    # Convert Mol to SVG
    d = MolDraw2DSVG(200, 200)
    d.DrawMolecule(mol)
    d.FinishDrawing()
    smiles_svg = d.GetDrawingText()

    # Set the SVG width and height to 100%
    smiles_svg = replace_svg_dimensions(smiles_svg)

    return smiles_svg
