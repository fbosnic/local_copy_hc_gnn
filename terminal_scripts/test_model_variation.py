import sys
import wandb
from pathlib import Path

import hamgnn.constants as constants
import hamgnn.model_utils as model_utils

if __name__ == "__main__":
    args = sys.argv
    if len(args) != 2:
        print("Please provide a checkpoint or weights and biases id of the model")
        exit(-31)
    identifier = args[-1]
    wandb_project = constants.WEIGHTS_AND_BIASES_PROJECT

    model = None
    wandb_run = None
    checkpoint_path = Path(identifier)
    if checkpoint_path.exists():
        try:
            model = model_utils.create_model_from_checkpoint(checkpoint_path)
            if model is None:
                print(f"Failed to create model from {checkpoint_path}. Appropriate model classes seem to be missing.")
        except Exception as ex:
            if wandb_run is not None:
                wandb_run.finish()
            wandb_run = None
            model = None

    if model is None or wandb_run is None:
        try:
            wandb_id = identifier
            wandb_run = wandb.init(project=wandb_project, id=wandb_id, resume=True)
            model = model_utils.create_model_for_wandb_run(wandb_run, wandb_run.config["checkpoint"])
            if model is None:
                print("Identified wandb run but failed to create the model for it")
        except Exception as ex:
            if wandb_run is not None:
                wandb_run.finish()
            wandb_run = None
            model = None


    if wandb_run is None or model is None:
        print(f"Could not identify model through '{identifier}'")
        exit(-2)
    else:
        results = model_utils.test_on_saved_data(model, wandb_run=wandb_run)
        print(results)
        wandb_run.finish()
