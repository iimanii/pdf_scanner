import requests
import json

class VirusTotal:
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://www.virustotal.com/api/v3"
        self.headers = {"X-Apikey": api_key}
    
    def upload_file(self, file_path):
        """Upload file to VirusTotal and return analysis ID"""
        url = f"{self.base_url}/files"
        
        with open(file_path, 'rb') as f:
            files = {'file': f}
            headers = {"X-Apikey": self.api_key}
            
            response = requests.post(url, files=files, headers=headers)
            response.raise_for_status()
            
            return response.json()['data']['id']
    
    def get_analysis(self, analysis_id):
        """Get analysis results by analysis ID"""
        url = f"{self.base_url}/analyses/{analysis_id}"
        
        response = requests.get(url, headers=self.headers)
        response.raise_for_status()
        
        return response.json()
    
    def get_analysis_status(self, analysis_id):
        """Get just the status of an analysis"""
        analysis = self.get_analysis(analysis_id)
        return analysis['data']['attributes']['status']
    
    def is_analysis_complete(self, analysis_id):
        """Check if analysis is complete"""
        try:
            status = self.get_analysis_status(analysis_id)
            return status == 'completed'
        except requests.exceptions.RequestException:
            return False
