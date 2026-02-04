import matplotlib.pyplot as plt
import os
import pandas as pd

def generate_chart(data):
    if not data:
        return None
        
    # Convert to DataFrame for easier handling
    df = pd.DataFrame(data)
    
    # Sort by price
    df = df.sort_values(by='price', ascending=True)
    
    plt.figure(figsize=(10, 8))
    plt.barh(df['country'], df['price'], color='skyblue')
    
    plt.xlabel('Preço (@) em US$')
    plt.title('Cotação do Boi no Mundo')
    plt.grid(axis='x', linestyle='--', alpha=0.7)
    
    # Add value labels
    for i, v in enumerate(df['price']):
        plt.text(v, i, f' ${v:.2f}', va='center')
        
    output_path = '/tmp/chart.png'
    # Ensure directory exists if we were using a subdirectory, but /tmp is standard
    
    plt.tight_layout()
    plt.savefig(output_path)
    plt.close()
    
    return output_path
