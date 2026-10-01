"""Transformações JSON bruto -> DataFrames tipados (camada core).

Todas são funções PURAS: recebem o JSON já lido e devolvem DataFrames. Não acessam rede,
disco nem banco, então são testadas sem nenhum deles. Gravar no banco é papel de `oddvision.load`.
"""
