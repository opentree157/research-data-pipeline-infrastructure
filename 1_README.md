# Research Data Pipeline Infrastructure 

**Submission Deadline: EOD Wednesday May 27, 2026**

**Expected Time for Completion: 5-6 hours**

## Guidance and Expectations
- Please, copmlete this exercise on your own without assistance from others.
- Use of LLM's is permitted but not required. If you use LLM's, please do so wisely and be prepared to answer detailed questions about your code.
- Please develop the infrastructure in a way that makes it easily deployable to the cloud.
- If you are pressed for time, focus on delivering complete working sections of the pipeline.
- Please, do not deploy this infrastructure to the cloud.

## Objective

Build a scalable research data processing pipeline that ingests sensor data, processes it 
for anomaly detection, and serves results via a web API. The system must run locally but be cloud-ready.

## Requirements

1. **Data Pipeline**: Ingest CSV sensor readings (temperature, humidity, pressure) into PostgreSQL
2. **Processing**: Implement anomaly detection algorithm that flags readings >2 standard deviations from rolling mean
3. **Storage**: Store processed results back to database with anomaly flags and confidence scores  
4. **API**: REST endpoint to query anomaly data by date range and sensor ID
5. **Frontend**: Simple web interface displaying recent anomalies in a table
6. **Infrastructure**: Dockerize all components, use nginx as reverse proxy
7. **CI/CD**: GitHub Actions workflow that builds, tests, and deploys on PR merge to main

## Constraints

- Use Docker Compose for local orchestration
- Database must persist data between container restarts
- Processing should handle >10k records efficiently
- Include basic monitoring/health checks
- All configs in environment variables
- GitHub repository with proper README and documentation
- GitHub Actions CI/CD pipeline for automated deployment

## Provided Resources

- `generate_data.py`: Script to create test datasets of any size with controllable anomalies
- `anomaly_detector.py`: Sample implementation of the anomaly detection algorithm (you may use as-is or adapt)
- `DATA_GENERATOR_GUIDE.md`: Detailed usage guide for the data generator

## Deliverables

- **GitHub Repository**: Public repo with complete source code, functional CI/CD pipeline, and documentation
   - **CI/CD Pipeline**: GitHub Actions workflow for automated build/test/deploy
   - **Documentation**: Clear README with architecture decisions and deployment instructions
- **Local Environment**: Working Docker Compose setup + functionality to be demoed at the follow-up call
