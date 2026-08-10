module "exercise_data_table" {
  source     = "../../modules/dynamodb_table"
  table_name = "exercise_data"
}

module "health_metrics_table" {
  source     = "../../modules/dynamodb_table"
  table_name = "health_metrics"
}
