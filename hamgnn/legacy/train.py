import os

import torch
import torch.multiprocessing as mp

from hamgnn.Models import EncodeProcessDecodeAlgorithm, GatedGCNEmbedAndProcess, MODEL_WEIGHTS_FOLDER
from hamgnn.Trainers import SupervisedTrainFollowingHamiltonCycle, REINFORCE_WithLearnableBaseline
from hamgnn.data.GraphGenerators import ErdosRenyiGenerator, NoisyCycleBatchGenerator
from hamgnn.Evaluation import EvaluationScores
from hamgnn.constants import DEFAULT_HAMILTONIAN_PROBABILITY, MAX_NR_BATCHES_TO_USE_FOR_EVALUATION, GRAPH_DATA_DIRECTORY_SIZE_GENERALISATION


def train_HamS(is_load_weight=False, train_epochs=2000):
    HamS_model = EncodeProcessDecodeAlgorithm(is_load_weight, processor_depth=5, hidden_dim=32)
    HamS_trainer = SupervisedTrainFollowingHamiltonCycle(nr_epochs=train_epochs, iterations_per_epoch=100,
                                                         loss_type="entropy",
                                                         batch_size=8)
    HamS_generator = NoisyCycleBatchGenerator(num_nodes=25, expected_noise_edge_for_node=3, batch_size=8)
    HamS_optimizer = torch.optim.Adam(HamS_model.parameters(), 1e-4)
    HamS_trainer.train(HamS_generator, HamS_model, HamS_optimizer)
    return HamS_model


def train_HamR(is_load_weights=False, train_epochs=1000):
    HamR_model = GatedGCNEmbedAndProcess(is_load_weights, embedding_depth=8, processor_depth=5, hidden_dim=32)
    HamR_trainer = REINFORCE_WithLearnableBaseline(nr_epochs=train_epochs, iterations_in_epoch=100,
                                                   episodes_per_example=1, simulation_batch_size=1)
    HamR_generator = ErdosRenyiGenerator(num_nodes=25, hamilton_existence_probability=DEFAULT_HAMILTONIAN_PROBABILITY)
    HamR_optimizer = torch.optim.Adam(HamR_model.parameters(), 1e-5)
    HamR_trainer.train(HamR_generator, HamR_model, HamR_optimizer)
    return HamR_model


def evaluate_model(model, model_name):
    evaluations = EvaluationScores.evaluate_model_on_saved_data(model, MAX_NR_BATCHES_TO_USE_FOR_EVALUATION,
                                                                 GRAPH_DATA_DIRECTORY_SIZE_GENERALISATION)
    return EvaluationScores.compute_accuracy_scores(evaluations)


if __name__ == '__main__':
    mp.set_start_method("spawn")
    # torch.autograd.set_detect_anomaly(True)
    torch.set_num_threads(2)

    if not os.path.exists(MODEL_WEIGHTS_FOLDER):
        try:
            os.mkdir(MODEL_WEIGHTS_FOLDER)
        except Exception as ex:
            print(f"Failed to create {MODEL_WEIGHTS_FOLDER}. It is needed to store model weights")
            exit(-1)

    if len([p for p in os.listdir(MODEL_WEIGHTS_FOLDER) if p.endswith(".tar")]) == 0:
        hamS_is_load_weights = False
        hamR_is_load_weights = False
        hamS_epochs = 2000
        hamR_epochs = 1000
    else:
        hamS_is_load_weights = True
        hamR_is_load_weights = True
        hamS_epochs = 0
        hamR_epochs = 0

    # HamS_model = train_HamS(hamS_is_load_weights, hamS_epochs)
    # HamR_model = train_HamR(hamR_is_load_weights, hamR_epochs)
    # HamS_evaluation_result = evaluate_model(HamS_model, "HamS")
    # HamR_evaluation_result = evaluate_model(HamR_model, "HamR")

    with mp.Pool(processes=2) as pool:
        HamS_train_result = pool.apply_async(train_HamS, (hamS_is_load_weights, hamS_epochs))
        HamR_train_result = pool.apply_async(train_HamR, (hamR_is_load_weights, hamR_epochs))
        HamS_model = HamS_train_result.get()
        HamR_model = HamR_train_result.get()
        for name, result in [("HamS", HamS_train_result), ("HamR", HamR_train_result)]:
            print(f"{name} train {'successful.' if result.successful() else 'failed!'}")

        HamS_evaluation_result = pool.apply_async(evaluate_model, (HamS_model, "HamS"))
        HamR_evaluation_result = pool.apply_async(evaluate_model, (HamR_model, "HamR"))
        HamS_evaluation_result.get()
        HamR_evaluation_result.get()

        for name, result in [("Hams", HamS_evaluation_result), ("HamR", HamR_evaluation_result)]:
            scores = result.get()
            print(f"{name} evaluation {'successful.' if result.successful() else 'failed!'}")
            if result.successful():
                print(f"{name} found Hamiltonian cycles in on graphs of sizes"
                      f" {[x for x in scores['size']]} in following fractions: {[x for x in scores['perc_ham_cycle']]}")
