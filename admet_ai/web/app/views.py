"""Defines the routes of the ADMET-AI Flask app."""
from uuid import uuid4
from tempfile import NamedTemporaryFile

import pandas as pd
from flask import (
    after_this_request,
    jsonify,
    render_template,
    request,
    Response,
    send_file,
    session,
)

from admet_ai.physchem_compute import compute_physicochemical_properties
from admet_ai.web.app import app
from admet_ai.web.app.admet_info import get_admet_info
from admet_ai.web.app.drugbank import (
    compute_drugbank_percentile,
    get_drugbank_task_names,
    get_drugbank_unique_atc_codes,
)
from admet_ai.web.app.models import get_admet_model
from admet_ai.web.app.plot import (
    plot_drugbank_reference,
    plot_molecule_svg,
    plot_radial_summary,
)
from admet_ai.web.app.storage import (
    get_user_preds,
    set_user_preds,
    update_user_activity,
)
from admet_ai.web.app.utils import (
    get_smiles_from_request,
    smiles_to_mols,
    string_to_html_sup,
)


DRUGBANK_APPROVED_PERCENTILE_SUFFIX = "drugbank_approved_percentile"


def render(**kwargs) -> str:
    """Renders the page with specified kwargs"""
    return render_template(
        "index.html",
        admet_info=get_admet_info(),
        drugbank_atc_codes=["all"] + get_drugbank_unique_atc_codes(),
        drugbank_tasks=get_drugbank_task_names(),
        max_molecules=app.config["MAX_MOLECULES"],
        low_performance_threshold=app.config["LOW_PERFORMANCE_THRESHOLD"],
        drugbank_approved_percentile_suffix=DRUGBANK_APPROVED_PERCENTILE_SUFFIX,
        heartbeat_frequency=app.config["HEARTBEAT_FREQUENCY"],
        string_to_html_sup=string_to_html_sup,
        **kwargs,
    )


@app.route("/", methods=["GET", "POST"])
def index():
    """Renders the page and makes predictions if the method is POST."""
    # Set up warnings
    warnings = []

    # Assign user ID to session
    if "user_id" not in session:
        session["user_id"] = uuid4().hex

    # If GET request, simply return the page; otherwise if POST request, make predictions
    if request.method == "GET":
        return render()

    # Get the SMILES from the request
    all_smiles = get_smiles_from_request()

    # Error if too many molecules
    if (
        app.config["MAX_MOLECULES"] is not None
        and len(all_smiles) > app.config["MAX_MOLECULES"]
    ):
        return render(
            errors=[
                f"Received too many molecules. Maximum number of molecules is {app.config['MAX_MOLECULES']:,}."
            ]
        )

    # Convert SMILES to RDKit molecules
    mols = smiles_to_mols(all_smiles)

    # Warn if any molecules are invalid
    num_invalid_mols = sum(mol is None for mol in mols)
    if num_invalid_mols > 0:
        ending = "s" if num_invalid_mols > 1 else ""
        warnings.append(
            f"Input contains {num_invalid_mols:,} invalid SMILES string{ending}."
        )

    # Remove invalid molecules
    all_smiles = [smile for smile, mol in zip(all_smiles, mols) if mol is not None]
    mols = [mol for mol in mols if mol is not None]

    # Error if no valid molecules
    if len(all_smiles) == 0:
        return render(errors=["No valid SMILES strings given."])

    # Compute physicochemical properties
    physchem_preds = compute_physicochemical_properties(
        all_smiles=all_smiles, mols=mols
    )

    # Make ADMET predictions
    admet_model = get_admet_model()
    admet_preds = admet_model.predict(smiles=all_smiles)

    # Combine physicochemical and ADMET properties
    all_preds = pd.concat((physchem_preds, admet_preds), axis=1)

    # Compute DrugBank percentiles
    drugbank_percentiles = pd.DataFrame(
        data={
            f"{property_name}_{DRUGBANK_APPROVED_PERCENTILE_SUFFIX}": compute_drugbank_percentile(
                property_name=property_name,
                predictions=all_preds[property_name].values,
                atc_code=session.get("atc_code"),
            )
            for property_name in all_preds.columns
        },
        index=all_smiles,
    )

    # Combine predictions and percentiles
    all_preds_with_drugbank = pd.concat((all_preds, drugbank_percentiles), axis=1)

    # Convert predictions to a dictionary mapping SMILES to property name to value
    smiles_to_property_id_to_pred: dict[
        str, dict[str, float]
    ] = all_preds_with_drugbank.to_dict(orient="index")

    # Store predictions in memory
    set_user_preds(user_id=session["user_id"], preds_df=all_preds_with_drugbank)

    # Create DrugBank reference plot
    drugbank_plot_svg = plot_drugbank_reference(
        preds_df=all_preds_with_drugbank,
        x_property_name=session.get("drugbank_x_task_name"),
        y_property_name=session.get("drugbank_y_task_name"),
        atc_code=session.get("atc_code"),
        max_molecule_num=app.config["MAX_VISIBLE_MOLECULES"],
    )

    # Get maximum number of molecules to display
    num_display_molecules = min(len(all_smiles), app.config["MAX_VISIBLE_MOLECULES"])

    # Create molecule SVG images
    mol_svgs = [plot_molecule_svg(mol) for mol in mols[:num_display_molecules]]

    # Create molecule radial plots for DrugBank approved percentiles
    radial_svgs = [
        plot_radial_summary(
            property_id_to_percentile=smiles_to_property_id_to_pred[smiles],
            percentile_suffix=DRUGBANK_APPROVED_PERCENTILE_SUFFIX,
        )
        for smiles in all_smiles[:num_display_molecules]
    ]

    return render(
        predicted=True,
        all_smiles=all_smiles,
        smiles_to_property_id_to_pred=smiles_to_property_id_to_pred,
        mol_svgs=mol_svgs,
        radial_svgs=radial_svgs,
        drugbank_plot=drugbank_plot_svg,
        num_molecules=len(all_smiles),
        num_display_molecules=num_display_molecules,
        warnings=warnings,
    )


@app.route("/drugbank_plot", methods=["GET"])
def drugbank_plot():
    # Get requested ATC code
    session["atc_code"] = request.args.get(
        "atc_code", default=session.get("atc_code"), type=str
    )

    # Get requested X and Y axes
    session["drugbank_x_task_name"] = request.args.get(
        "x_task", default=session.get("drugbank_x_task_name"), type=str
    )
    session["drugbank_y_task_name"] = request.args.get(
        "y_task", default=session.get("drugbank_y_task_name"), type=str
    )

    # Create DrugBank reference plot with ATC code
    drugbank_plot_svg = plot_drugbank_reference(
        preds_df=get_user_preds(session["user_id"]),
        x_property_name=session["drugbank_x_task_name"],
        y_property_name=session["drugbank_y_task_name"],
        atc_code=session["atc_code"],
        max_molecule_num=app.config["MAX_VISIBLE_MOLECULES"],
    )

    return jsonify({"svg": drugbank_plot_svg})


@app.route("/download_predictions")
def download_predictions() -> Response:
    """Downloads predictions as a CSV file."""
    # Create a temporary file to hold the predictions
    preds_file = NamedTemporaryFile()

    # Set up a function to close the file after the response is sent
    @after_this_request
    def remove_file(response: Response) -> Response:
        preds_file.close()
        return response

    # Save predictions to temporary file
    get_user_preds(session["user_id"]).to_csv(preds_file.name, index=False)
    preds_file.seek(0)

    # Return the temporary file as a response
    return send_file(
        preds_file.name, as_attachment=True, download_name="predictions.csv"
    )


@app.route("/heartbeat", methods=["POST"])
def heartbeat() -> tuple[str, int]:
    """Registers that the client is still using the site.

    :return: A tuple containing an empty string and a 204 status code.
    """
    # Update user's last activity
    session.modified = True

    if "user_id" in session:
        update_user_activity(session["user_id"])

    # Send no content response
    return "", 204
